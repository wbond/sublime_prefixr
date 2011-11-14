import sublime
import sublime_plugin
import urllib
import urllib2
import threading
import re


class PrefixrCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        # We check for braces since we can do a better job of preserving
        # whitespace when braces are not present
        braces = False
        sels = self.view.sel()
        for sel in sels:
            if self.view.substr(sel).find('{') != -1:
                braces = True

        # Expand selection to braces, unfortunately this can't use the
        # built in move_to brackets since that matches parentheses also
        if not braces:
            new_sels = []
            for sel in sels:
                new_sels.append(self.view.find('\}', sel.end()))
            sels.clear()
            for sel in new_sels:
                sels.add(sel)
            self.view.run_command("expand_selection", {"to": "brackets"})

        # We start one thread per selection so we don't lock up the interface
        # while waiting for the response from the API
        threads = []
        for sel in sels:
            string = self.view.substr(sel)
            thread = PrefixrApiCall(sel, string, 5)
            threads.append(thread)
            thread.start()

        # We clear all selection because we are going to manually set them
        self.view.sel().clear()

        # This creates an edit group so we can undo all changes in one go
        edit = self.view.begin_edit('prefixr')

        self.handle_threads(edit, threads, braces)

    def handle_threads(self, edit, threads, braces, offset=0, i=0, dir=1):
        next_threads = []
        for thread in threads:
            if thread.is_alive():
                next_threads.append(thread)
                continue
            if thread.result == False:
                continue
            offset = self.replace(edit, thread, braces, offset)
        threads = next_threads

        if len(threads):
            # This animates a little activity indicator in the status area
            before = i % 8
            after = (7) - before
            if not after:
                dir = -1
            if not before:
                dir = 1
            i += dir
            self.view.set_status('prefixr', 'Prefixr [%s=%s]' % \
                (' ' * before, ' ' * after))

            sublime.set_timeout(lambda: self.handle_threads(edit, threads,
                braces, offset, i, dir), 100)
            return

        self.view.end_edit(edit)

        self.view.erase_status('prefixr')
        selections = len(self.view.sel())
        sublime.status_message('Prefixr successfully run on %s selection%s' %
            (selections, '' if selections == 1 else 's'))

    def replace(self, edit, thread, braces, offset):
        sel = thread.sel
        original = thread.original
        result = thread.result

        # Here we adjust each selection for any text we have already inserted
        if offset:
            sel = sublime.Region(sel.begin() + offset,
                sel.end() + offset)

        result = self.normalize_line_endings(result)
        (prefix, main, suffix) = self.fix_whitespace(original, result, sel,
            braces)
        self.view.replace(edit, sel, prefix + main + suffix)

        # We add the end of the new text to the selection
        end_point = sel.begin() + len(prefix) + len(main)
        self.view.sel().add(sublime.Region(end_point, end_point))

        return offset + len(prefix + main + suffix) - len(original)

    def normalize_line_endings(self, string):
        string = string.replace('\r\n', '\n').replace('\r', '\n')
        line_endings = self.view.settings().get('default_line_ending')
        if line_endings == 'windows':
            string = string.replace('\n', '\r\n')
        elif line_endings == 'mac':
            string = string.replace('\n', '\r')
        return string

    def fix_whitespace(self, original, prefixed, sel, braces):
        # If braces are present we can do all of the whitespace magic
        if braces:
            return ('', prefixed, '')

        # Determine the indent of the CSS rule
        (row, col) = self.view.rowcol(sel.begin())
        indent_region = self.view.find('^\s+', self.view.text_point(row, 0))
        if indent_region and self.view.rowcol(indent_region.begin())[0] == row:
            indent = self.view.substr(indent_region)
        else:
            indent = ''

        # Strip whitespace from the prefixed version so we get it right
        prefixed = prefixed.strip()
        prefixed = re.sub(re.compile('^\s+', re.M), '', prefixed)

        # Indent the prefixed version to the right level
        settings = self.view.settings()
        use_spaces = settings.get('translate_tabs_to_spaces')
        tab_size = int(settings.get('tab_size', 8))
        indent_characters = '\t'
        if use_spaces:
            indent_characters = ' ' * tab_size
        prefixed = prefixed.replace('\n', '\n' + indent + indent_characters)

        match = re.search('^(\s*)', original)
        prefix = match.groups()[0]
        match = re.search('(\s*)\Z', original)
        suffix = match.groups()[0]

        return (prefix, prefixed, suffix)


class PrefixrApiCall(threading.Thread):
    def __init__(self, sel, string, timeout):
        self.sel = sel
        self.original = string
        self.timeout = timeout
        self.result = None
        threading.Thread.__init__(self)

    def run(self):
        try:
            data = urllib.urlencode({'css': self.original})
            request = urllib2.Request('http://prefixr.com/api/index.php', data,
                headers={"User-Agent": "Sublime Prefixr"})
            http_file = urllib2.urlopen(request, timeout=self.timeout)
            self.result = http_file.read()
            return

        except (urllib2.HTTPError) as (e):
            err = '%s: HTTP error %s contacting API' % (__name__, str(e.code))
        except (urllib2.URLError) as (e):
            err = '%s: URL error %s contacting API' % (__name__, str(e.reason))

        sublime.error_message(err)
        self.result = False
