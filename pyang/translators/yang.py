"""YANG output plugin"""

import optparse
import re

from .. import plugin
from .. import util
from .. import grammar

def pyang_plugin_init():
    plugin.register_plugin(YANGPlugin())

class YANGPlugin(plugin.PyangPlugin):
    def add_output_format(self, fmts):
        fmts['yang'] = self
        self.handle_comments = True

    def add_opts(self, optparser):
        optlist = [
            optparse.make_option("--yang-canonical",
                                 dest="yang_canonical",
                                 action="store_true",
                                 help="Print in canonical order"),
            optparse.make_option("--yang-remove-unused-imports",
                                 dest="yang_remove_unused_imports",
                                 action="store_true"),
            optparse.make_option("--yang-keep-blank-lines",
                                 dest="yang_keep_blank_lines",
                                 action="store_true",
                                 help="Keep blank lines and trailing comments")
            ]
        g = optparser.add_option_group("YANG output specific options")
        g.add_options(optlist)

    def emit(self, ctx, modules, fd):
        hooks = YANGEmitHooks()
        module = modules[0]
        emit_yang(ctx, hooks, module, fd)

class YANGEmitHooks:
    """Hooks called while emitting YANG"""

    def emit_stmt_hook(self, ctx, stmt, level):
        """Called on entry to emit_stmt()"""
        pass

def emit_yang(ctx, hooks, module, fd):
    stmts = module.real_parent.substmts if module.real_parent else [module]
    for (i, stmt) in enumerate(stmts):
        next_stmt = stmts[i+1] if (i < len(stmts) - 1) else None
        emit_stmt(ctx, hooks, stmt, fd, 0, None, next_stmt, False, '', '  ')

_force_newline_arg = ('description', 'contact', 'organization', 'reference')
_non_quote_arg_type = ('identifier', 'identifier-ref', 'boolean', 'integer',
                       'non-negative-integer', 'max-value',
                       'date', 'ordered-by-arg',
                       'fraction-digits-arg', 'deviate-arg', 'version',
                       'status-arg')

_maybe_quote_arg_type = ('enum-arg', )

_kwd_class = {
    'yang-version': 'header',
    'namespace': 'header',
    'prefix': 'header',
    'belongs-to': 'header',
    'organization': 'meta',
    'contact': 'meta',
    'description': 'meta',
    'reference': 'meta',
    'import': 'linkage',
    'include': 'linkage',
    'revision': 'revision',
    'typedef': 'defs',
    'grouping': 'defs',
    'identity': 'defs',
    'feature': 'defs',
    'extension': 'defs',
    '_comment': 'comment',
    'module': None,
    'submodule': None,
}
def get_kwd_class(keyword):
    if util.is_prefixed(keyword):
        return 'extension'
    else:
        try:
            return _kwd_class[keyword]
        except KeyError:
            return 'body'

_keyword_with_trailing_newline = (
    'typedef',
    'grouping',
    'identity',
    'feature',
    'extension',
    'rpc',
    'notification',
    )

_keyword_prefer_squote_arg = (
    'must',
    'when',
    'pattern',
    )

_need_quote = (
    " ", "}", "{", ";", '"', "'",
    "\n", "\t", "\r", "//", "/*", "*/",
    )

def emit_stmt(ctx, hooks, stmt, fd, level, prev_kwd_class, next_stmt,
              no_indent, indent, indentstep):
    hooks.emit_stmt_hook(ctx, stmt, level)

    if ctx.opts.yang_remove_unused_imports and stmt.keyword == 'import':
        for p in stmt.parent.i_unused_prefixes:
            if stmt.parent.i_unused_prefixes[p] == stmt:
                return

    if util.is_prefixed(stmt.raw_keyword):
        (prefix, identifier) = stmt.raw_keyword
        keywordstr = prefix + ':' + identifier
    else:
        keywordstr = stmt.keyword

    # XXX is this safe? parent is clearly manipulated by augment etc; better
    #     to pass it in as (yet another) argument?
    prev_stmt = stmt.parent \
                if stmt.parent and stmt.parent.substmts and \
                   stmt.parent.substmts[0] is stmt else None
    newlines_before = get_newlines_before(prev_stmt, stmt) \
                      if ctx.opts.yang_keep_blank_lines else 0
    if newlines_before > 0:
        fd.write(newlines_before * '\n')

    # XXX is this safe? parent is clearly manipulated by augment etc; better
    #     to pass it in as (yet another) argument?
    prev_stmt = stmt.parent \
                if stmt.parent and stmt.parent.substmts[0] is stmt else None
    newlines_before = get_newlines_before(prev_stmt, stmt) \
                      if ctx.opts.yang_keep_blank_lines else 0
    if newlines_before > 0:
        fd.write(newlines_before * '\n')

    kwd_class = get_kwd_class(stmt.keyword)
    # WL these two lines are in master
    #if not ctx.opts.yang_keep_blank_lines and \
    #   ((level == 1 and
    # WL this line is my code
    if ((level == 1 and not ctx.opts.yang_keep_blank_lines and
         kwd_class != prev_kwd_class and kwd_class != 'extension') or
        stmt.keyword in _keyword_with_trailing_newline):
        fd.write('\n')

    # WL this code is in master
    #if stmt.keyword == '_comment':
    #    emit_comment(stmt.arg, fd, indent)
    # WL this is my code
    newlines_after = get_newlines_after(stmt, next_stmt) \
                     if ctx.opts.yang_keep_blank_lines else 1
    stmt_term = newlines_after * '\n' if newlines_after > 0 else ' '
    # XXX uncomment this to debug --yang-keep-blank-lines
    #stmt_term = ' ' + pos_range(stmt) + ' ' + str(newlines_after) + stmt_term

    if keyword == '_comment':
        emit_comment(stmt.arg, fd, '' if no_indent else indent)
        fd.write(stmt_term)
    # WL end
        return

    fd.write(indent + keywordstr)
    if stmt.arg != None:
        if (stmt.keyword in _keyword_prefer_squote_arg and
            stmt.arg.find("'") == -1):
            fd.write(" '" + stmt.arg + "'")
        elif stmt.keyword in grammar.stmt_map:
            (arg_type, _subspec) = grammar.stmt_map[stmt.keyword]
            if arg_type in _non_quote_arg_type:
                fd.write(' ' + stmt.arg)
            # WL this is in master
            elif (arg_type in _maybe_quote_arg_type and
                  not need_quote(stmt.arg)):
                fd.write(' ' + stmt.arg)
            # WL this is in my version
            elif keyword in ['augment', 'must', 'path', 'pattern', 'when']:
                # XXX is there a generic way of knowing which statements
                #     need this treatment?
                emit_arg_squote(keyword, stmt.arg, fd, indent, indentstep,
                                ctx.max_line_len)
            # WL end
            else:
                emit_arg(stmt, fd, indent, indentstep)
        else:
            emit_arg(stmt, fd, indent, indentstep)

    if len(stmt.substmts) == 0:
        fd.write(';' + stmt_term)
    else:
        fd.write(' {\n')
        if ctx.opts.yang_canonical:
            substmts = grammar.sort_canonical(stmt.keyword, stmt.substmts)
        else:
            substmts = stmt.substmts
        if level == 0:
            kwd_class = 'header'
        for (i, s) in enumerate(substmts):
            n = substmts[i+1] if (i < len(substmts) - 1) else None
            no_indent = emit_stmt(ctx, hooks, s, fd, level + 1, kwd_class, n,
                                  no_indent, indent + indentstep, indentstep)
            kwd_class = get_kwd_class(s.keyword)
        fd.write(indent + '}' + stmt_term)
    return (newlines_after == 0)

def emit_arg_squote(keyword, arg, fd, indent, indentstep, max_line_len):
    """Heuristically pretty print the argument with smart quotes"""

    # use single quotes unless the arg contains a single quote
    quote = "'" if arg.find("'") == -1 else '"'

    # if using double quotes, replace special characters
    if quote == '"':
        arg = arg.replace('\\', r'\\')
        arg = arg.replace('"', r'\"')
        arg = arg.replace('\t', r'\t')

    # if there aren't any characters that require quoting, don't quote
    # XXX no, it's more complicated than this; will need to quote anyway
    #     if have to split the argument into multiple lines
    #mustquote = [" ", "\t", "\n", "'", '"', ";", "{", "}", "//", "/*", "*/"]
    #if not [True for c in arg if c in mustquote]:
    #    quote = ""

    # XXX allow for " {" even though the statement might not have sub-
    #     statements; don't consider trailing comments
    term = " {"

    line_len = len("%s%s %s%s%s%s" % (indent, keyword,
                                      quote, arg, quote, term))
    if max_line_len is None or line_len <= max_line_len:
        fd.write(" " + quote + arg + quote)
        return

    # XXX can't guarantee to split the argument in the same way as it
    #     was originally split (not enough information) so do it naively
    # XXX strictly num_chars could be negative, e.g. if max_line_len is VERY
    #     small; should check for this
    num_chars = len(arg) - (line_len - max_line_len)
    # WL these two lines are my code?
    while num_chars > 2 and arg[num_chars-1:num_chars].isalnum():
        num_chars -= 1
    fd.write(" " + quote + arg[:num_chars] + quote)
    arg = arg[num_chars:]
    while arg != '':
        keyword_cont = ((len(keyword) - 1) * ' ') + '+'
        line_len = len("%s%s %s%s%s%s" % (indent, keyword_cont,
                                          quote, arg, quote, term))
        num_chars = len(arg) - (line_len - max_line_len)
        # WL these two lines are my code?
        while num_chars > 2 and arg[num_chars-1:num_chars].isalnum():
            num_chars -= 1
        fd.write('\n' + indent + keyword_cont + " " +
                 quote + arg[:num_chars] + quote)
        arg = arg[num_chars:]

def emit_arg(stmt, fd, indent, indentstep):
    """Heuristically pretty print the argument string"""
    # current alg. always print a double quoted string
    arg = stmt.arg
    arg = arg.replace('\\', r'\\')
    arg = arg.replace('"', r'\"')
    arg = arg.replace('\t', r'\t')
    lines = arg.splitlines(True)
    if len(lines) <= 1:
        if len(arg) > 0 and arg[-1] == '\n':
            arg = arg[:-1] + r'\n'
        if stmt.keyword in _force_newline_arg:
            fd.write('\n' + indent + indentstep + '"' + arg + '"')
        else:
            fd.write(' "' + arg + '"')
    else:
        fd.write('\n')
        fd.write(indent + indentstep + '"' + lines[0])
        for line in lines[1:-1]:
            # WL this line is in master
            #if line[0] == '\n':
            # WL this line is my code
            if line.strip() == '':
                fd.write('\n')
            else:
                fd.write(indent + indentstep + ' ' + line)
        # write last line
        fd.write(indent + indentstep + ' ' + lines[-1])
        if lines[-1][-1] == '\n':
            # last line ends with a newline, indent the ending quote
            fd.write(indent + indentstep + '"')
        else:
            fd.write('"')

def emit_comment(comment, fd, indent):
    lines = comment.splitlines(True)
    for x in lines:
        if x[0] == '*':
            fd.write(indent + ' ' + x)
        elif x.strip() == '':
            fd.write('\n')
        else:
            fd.write(indent + x)
    fd.write('\n')

def need_quote(arg):
    for ch in _need_quote:
        if arg.find(ch) != -1:
            return True
    return False

# WL this is my code
def get_newlines_before(prev_stmt, this_stmt):
    newlines_before = 0
    if prev_stmt and prev_stmt.pos and this_stmt.pos_begin:
        prev_stmt_line = prev_stmt.pos.line
        this_stmt_begin_line = this_stmt.pos_begin.line
        newlines_before = this_stmt_begin_line - prev_stmt_line
        if newlines_before > 0:
            newlines_before -= 1
    return newlines_before

def get_newlines_before(prev_stmt, this_stmt):
    newlines_before = 0
    if prev_stmt and prev_stmt.pos and this_stmt.pos_begin:
        prev_stmt_line = prev_stmt.pos.line
        this_stmt_begin_line = this_stmt.pos_begin.line
        newlines_before = this_stmt_begin_line - prev_stmt_line
        if newlines_before > 0:
            newlines_before -= 1
    return newlines_before

def get_newlines_after(this_stmt, next_stmt):
    newlines_after = 1
    if this_stmt.pos_end and next_stmt and next_stmt.pos_begin:
        this_stmt_end_line = this_stmt.pos_end.line
        next_stmt_begin_line = next_stmt.pos_begin.line
        newlines_after = next_stmt_begin_line - this_stmt_end_line
    return newlines_after

# FIXME: tmp debug
def pos_range(stmt):
    s = "[%s" % stmt.pos_begin
    if stmt.pos.line > stmt.pos_begin.line:
        s += "-%d" % stmt.pos.line
    if stmt.pos_end.line > stmt.pos.line:
        s += "->%d" % stmt.pos_end.line
    s += "]"
    return s
# WL end
