"""TypeScript extractor (tree-sitter): mirrors the Python extractor's
resolution model and output structures (S1 boundary).

Module ids are source-tree-relative posix paths without extension
(`services/orders`), not dotted names. Resolution model, mirroring
`generate._ModuleIndex`:

  - `import { fn } from "./x"` + `fn()`              → services/x:fn
  - `import { fn as f } from "./x"` + `f()`          → services/x:fn
  - `import * as ns from "./x"` + `ns.sub.fn()`      → services/x:sub.fn
  - `import mod from "./x"` + `mod()` / `mod.fn()`   → services/x[:fn]
  - calls to top-level names defined in the same module → services/x:name
  - everything else (obj.method(), this.m(), locals, aliased/external
    imports, builtins)                                → Unresolved

Relative import sources ("./x", "../a/x") resolve to in-tree modules by
trying `<dir>.ts`, `<dir>.tsx`, `<dir>/index.ts` against the parsed module
set. Non-relative sources (npm packages, path aliases like `@/x`) bind to
nothing, so calls through them land in Unresolved — path-alias resolution
is deliberately out of scope here.
"""

from __future__ import annotations

from pathlib import Path


def _shared():
    """Lazy import of the generate module's shared structures: keeps this
    module importable without a circular dependency on generate."""
    from .generate import CallSite, Interface, UnresolvedTarget, _in_tree_module_prefixes

    return CallSite, Interface, UnresolvedTarget, _in_tree_module_prefixes


def _language(suffix: str = ".ts"):
    import tree_sitter
    import tree_sitter_typescript

    if suffix == ".tsx":
        lang = tree_sitter.Language(tree_sitter_typescript.language_tsx())
    else:
        lang = tree_sitter.Language(tree_sitter_typescript.language_typescript())
    try:
        return tree_sitter.Parser(lang)
    except TypeError:  # py-tree-sitter < 0.22
        parser = tree_sitter.Parser()
        parser.set_language(lang)
        return parser


def _module_of(base: Path, file: Path) -> str:
    rel = file.relative_to(base).with_suffix("")
    return "/".join(rel.parts)


def _chain_of(node) -> list[str] | None:
    """Flatten identifier/member_expression into dotted parts; None if the
    root is not a plain identifier (this, call result, element access...)."""
    parts: list[str] = []
    while node.type == "member_expression":
        parts.append(node.child_by_field_name("property").text.decode())
        node = node.child_by_field_name("object")
    if node.type == "identifier":
        parts.append(node.text.decode())
        return list(reversed(parts))
    return None


_DECL_TYPES = ("function_declaration", "class_declaration")


def _declaration_of(node):
    """The declaration under a top-level node, unwrapping `export`."""
    if node.type in _DECL_TYPES:
        return node
    if node.type == "export_statement":
        for child in node.children:
            if child.type in _DECL_TYPES:
                return child
    return None


def _top_level_defs(root) -> tuple[set[str], list[tuple[str, str]]]:
    """(top-level names, (module-id, qualname) definitions) per tree-sitter
    node types from the issue #20 constraint list."""
    names: set[str] = set()
    defs: list[tuple[str, str]] = []
    for node in root.children:
        decl = _declaration_of(node)
        if decl is None:
            continue
        name = decl.child_by_field_name("name").text.decode()
        names.add(name)
        defs.append((name, name))
        if decl.type == "class_declaration":
            for child in decl.children:
                if child.type == "class_body":
                    for member in child.children:
                        if member.type == "method_definition":
                            mname = member.child_by_field_name("name").text.decode()
                            defs.append((f"{name}.{mname}", f"{name}.{mname}"))
    return names, defs


def _import_bindings(root, module: str, parsed_modules: set[str]) -> dict[str, str | None]:
    """alias -> binding. Binding is `module:name` (named), `module`
    (namespace/default), or None (external: package or unresolvable alias
    source). Mirrors _ModuleIndex.imports."""
    binds: dict[str, str | None] = {}
    for node in root.children:
        if node.type != "import_statement":
            continue
        source_node = node.child_by_field_name("source")
        target = _resolve_import_source(
            source_node.text.decode().strip("'\""), module, parsed_modules
        )
        for child in node.children:
            if child.type == "import_clause":
                for part in child.children:
                    if part.type == "identifier":  # default import
                        binds[part.text.decode()] = target
                    elif part.type == "namespace_import":
                        alias = part.text.decode().split()[-1]
                        binds[alias] = target
                    elif part.type == "named_imports":
                        for spec in part.children:
                            if spec.type != "import_specifier":
                                continue
                            name = spec.child_by_field_name("name").text.decode()
                            alias_node = spec.child_by_field_name("alias")
                            binds[alias_node.text.decode() if alias_node else name] = (
                                f"{target}:{name}" if target else None
                            )
    return binds


def _resolve_import_source(source: str, module: str, parsed_modules: set[str]) -> str | None:
    """Resolve an import source string to an in-tree module id, or None."""
    if not source.startswith("."):
        return None  # npm package or path alias: not resolved here
    base_dir = module.rsplit("/", 1)[0] if "/" in module else ""
    # Pop against the joint stack so traversal may pass through and beyond
    # the importing module's own directory into parent directories.
    stack: list[str] = base_dir.split("/") if base_dir else []
    for seg in source.split("/"):
        if seg in (".", ""):
            continue
        elif seg == "..":
            if stack:
                stack.pop()
        else:
            stack.append(seg)
    stem = "/".join(stack)
    for candidate in (stem, f"{stem}/index"):
        if candidate in parsed_modules:
            return candidate
    return None


def _resolve(binds: dict[str, str | None], names: set[str],
             chain: list[str], module: str) -> str | None:
    root, rest = chain[0], chain[1:]
    binding = binds.get(root)
    if binding is not None:
        if ":" in binding:
            return binding + ("." + ".".join(rest) if rest else "")
        return binding + (":" + ".".join(rest) if rest else "")
    if root in names:
        return module + ":" + ".".join(chain)
    return None


def _walk(node, stack: list[str], module: str, rel: str,
          binds: dict, names: set[str], interfaces: dict, unresolved: dict) -> None:
    if node.type in ("function_declaration", "class_declaration",
                     "method_definition"):
        stack = stack + [node.child_by_field_name("name").text.decode()]
    if node.type == "call_expression":
        chain = _chain_of(node.child_by_field_name("function"))
        site = CallSite(file=rel, symbol=".".join(stack) if stack else "<module>")
        if chain is None:
            unresolved.setdefault("<unresolvable>", UnresolvedTarget()).call_sites.add(site)
        else:
            ident = _resolve(binds, names, chain, module)
            if ident is None:
                unresolved.setdefault(".".join(chain), UnresolvedTarget()).call_sites.add(site)
            else:
                interfaces.setdefault(ident, Interface()).call_sites.add(site)
    for child in node.children:
        _walk(child, stack, module, rel, binds, names, interfaces, unresolved)


def collect(repo_root: Path, files: list[tuple[str, Path, Path]]):
    """Extractor contract (see generate.Extractor): returns
    (interfaces, unresolved, in_tree)."""
    CallSite, Interface, UnresolvedTarget, _in_tree_module_prefixes = _shared()
    globals().update(CallSite=CallSite, Interface=Interface,
                     UnresolvedTarget=UnresolvedTarget)
    parsers: dict[str, object] = {}

    def parser_for(suffix: str):
        if suffix not in parsers:
            parsers[suffix] = _language(suffix)
        return parsers[suffix]

    modules: dict[str, object] = {}
    top_names: dict[str, set[str]] = {}
    binds: dict[str, dict] = {}
    for rel, path, base in files:
        module = _module_of(base, path)
        tree = parser_for(path.suffix).parse(path.read_bytes())
        modules[module] = tree
        top_names[module], _defs = _top_level_defs(tree.root_node)
        binds[module] = {}  # filled after all modules are known
    parsed_modules = set(modules)
    for rel, path, base in files:
        module = _module_of(base, path)
        binds[module] = _import_bindings(modules[module].root_node, module, parsed_modules)

    interfaces: dict[str, Interface] = {}
    unresolved: dict[str, UnresolvedTarget] = {}
    for rel, path, base in files:
        module = _module_of(base, path)
        _walk(modules[module].root_node, [], module, rel, binds[module],
              top_names[module], interfaces, unresolved)
    return interfaces, unresolved, _in_tree_module_prefixes(parsed_modules)
