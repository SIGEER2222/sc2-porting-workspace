#!/usr/bin/env node
/**
 * Galaxy CLI Query Tool — one-shot Galaxy code intelligence for AI use.
 *
 * Usage:
 *   node galaxy-query.mjs index <dir1> [dir2 ...]       — index .galaxy files
 *   node galaxy-query.mjs lookup <symbolName>            — lookup global symbol
 *   node galaxy-query.mjs symbols [query]                — workspace symbol search
 *   node galaxy-query.mjs doc-symbols <file>              — document symbols
 *   node galaxy-query.mjs definition <file> <line> <char>— find definition
 *   node galaxy-query.mjs diagnostics <file>              — get diagnostics
 *   node galaxy-query.mjs help                            — show help
 *
 * State: index is stored in a cache dir (default: %TEMP%/galaxy-lsp-cache.json).
 *        Re-run `index` to refresh. Subsequent queries use the cached index.
 *
 * Env:
 *   GALAXY_LSP_BUNDLE  — path to sc2-lsp-lib.mjs (default: sibling reference toolkit)
 *   GALAXY_CACHE       — path to cache file (default: %TEMP%/galaxy-lsp-cache.json)
 */
import { pathToFileURL } from 'node:url';
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as os from 'node:os';

// ── Resolve sc2-lsp library bundle path ──
const DEFAULT_BUNDLE = 'e:/Code/MyMod/SC2VibeTools/sc2-porting-workspace/reference/sc2-galaxy-toolkit/packages/sc2-lsp/dist/sc2-lsp-lib.mjs';
const BUNDLE_PATH = process.env.GALAXY_LSP_BUNDLE || DEFAULT_BUNDLE;
const DEFAULT_CACHE = path.join(os.tmpdir(), 'galaxy-lsp-cache.json');
const CACHE_PATH = process.env.GALAXY_CACHE || DEFAULT_CACHE;

const sc2lsp = await import(pathToFileURL(BUNDLE_PATH).href);
const {
    Store,
    createTextDocument,
    createProvider,
    NavigationProvider,
    DefinitionProvider,
    DiagnosticsProvider,
    getPositionOfLineAndCharacter,
    getNodeRange,
    getSourceFileOfNode,
    SyntaxKind,
    SymbolFlags,
} = sc2lsp;

// ── Helpers ──
function fileUriToPath(uri) {
    if (uri.startsWith('file:///')) return decodeURIComponent(uri.slice('file://'.length));
    return uri;
}
function pathToFileUri(p) {
    let n = p.replace(/\\/g, '/');
    if (!n.startsWith('/')) n = '/' + n;
    return 'file://' + encodeURI(n);
}
function nodeKindName(node) {
    if (!node || typeof node.kind !== 'number') return 'unknown';
    for (const [name, val] of Object.entries(SyntaxKind)) { if (val === node.kind) return name; }
    return String(node.kind);
}
function symbolKindName(flags) {
    if (typeof flags !== 'number') return 'unknown';
    const parts = [];
    const flagNames = [
        ['Function', SymbolFlags.Function], ['Struct', SymbolFlags.Struct],
        ['GlobalVariable', SymbolFlags.GlobalVariable], ['LocalVariable', SymbolFlags.LocalVariable],
        ['FunctionParameter', SymbolFlags.FunctionParameter], ['Property', SymbolFlags.Property],
        ['Typedef', SymbolFlags.Typedef], ['Static', SymbolFlags.Static], ['Native', SymbolFlags.Native],
    ];
    for (const [name, val] of flagNames) {
        if (typeof val === 'number' && (flags & val) === val && val !== 0) parts.push(name);
    }
    return parts.length ? parts.join('|') : 'none';
}
function declarationToLoc(decl) {
    const sf = typeof getSourceFileOfNode === 'function' ? getSourceFileOfNode(decl) : decl;
    const range = getNodeRange(decl);
    const fileName = sf ? (sf.fileName || sf.uri || '') : '';
    return {
        file: fileName ? fileUriToPath(fileName) : '',
        line: range.start.line, character: range.start.character,
        endLine: range.end.line, endCharacter: range.end.character,
        kind: nodeKindName(decl),
    };
}
function findGalaxyFiles(dir) {
    const results = [];
    function walk(d) {
        let entries;
        try { entries = fs.readdirSync(d, { withFileTypes: true }); } catch { return; }
        for (const e of entries) {
            const full = path.join(d, e.name);
            if (e.isDirectory()) {
                if (e.name === 'node_modules' || e.name === '.git') continue;
                walk(full);
            } else if (e.name.endsWith('.galaxy') || e.name.endsWith('.galaxya')) {
                results.push(full);
            }
        }
    }
    walk(dir);
    return results;
}

// ── Store management ──
function createStore() {
    return new Store();
}
function createProviders(store) {
    return {
        navigation: createProvider(NavigationProvider, store),
        definition: createProvider(DefinitionProvider, store),
        diagnostics: createProvider(DiagnosticsProvider, store),
    };
}

// Serialization: the Store holds SourceFile objects with circular references.
// We can't JSON-serialize the store directly. Instead, for the cache we save
// a list of {uri, text} pairs and rebuild the store on load.
function saveCache(store) {
    const docs = [];
    for (const [uri, sf] of store.documents) {
        docs.push({ uri, text: sf.text || sf._text || '' });
    }
    const data = { version: 1, docs };
    fs.writeFileSync(CACHE_PATH, JSON.stringify(data), 'utf8');
    return docs.length;
}
function loadCache() {
    if (!fs.existsSync(CACHE_PATH)) return null;
    const data = JSON.parse(fs.readFileSync(CACHE_PATH, 'utf8'));
    if (!data.docs) return null;
    const store = createStore();
    for (const { uri, text } of data.docs) {
        const doc = createTextDocument(uri, text);
        store.updateDocument(doc);
    }
    return store;
}
function getStore() {
    const store = loadCache();
    if (!store) {
        console.error('No index found. Run: node galaxy-query.mjs index <dir>');
        process.exit(1);
    }
    return store;
}

// ── Commands ──
const COMMANDS = {
    async index(args) {
        if (args.length === 0) { console.error('Usage: index <dir1> [dir2 ...]'); process.exit(1); }
        const store = createStore();
        let count = 0;
        const errors = [];
        for (const dir of args) {
            const abs = path.resolve(dir);
            const files = findGalaxyFiles(abs);
            for (const f of files) {
                try {
                    const text = fs.readFileSync(f, 'utf8');
                    const uri = pathToFileUri(f);
                    store.updateDocument(createTextDocument(uri, text));
                    count++;
                } catch (e) { errors.push(`${f}: ${e.message}`); }
            }
        }
        const saved = saveCache(store);
        let symbolCount = 0;
        for (const doc of store.documents.values()) {
            if (doc.symbol?.members) symbolCount += doc.symbol.members.size;
        }
        console.log(JSON.stringify({
            filesIndexed: count,
            filesCached: saved,
            globalSymbols: symbolCount,
            errors,
        }, null, 2));
    },

    lookup(args) {
        const name = args[0];
        if (!name) { console.error('Usage: lookup <symbolName>'); process.exit(1); }
        const store = getStore();
        const sym = store.resolveGlobalSymbol(name);
        if (!sym) { console.log(JSON.stringify({ found: false })); return; }
        const decls = (sym.declarations || []).map(declarationToLoc);
        console.log(JSON.stringify({
            found: true, name: sym.escapedName,
            flags: symbolKindName(sym.flags), declarations: decls,
        }, null, 2));
    },

    symbols(args) {
        const query = args[0] || '';
        const store = getStore();
        const { navigation } = createProviders(store);
        const decls = navigation.getWorkspaceSymbols(query);
        const result = decls.map(d => ({
            name: d.name?.name || '', kind: nodeKindName(d), ...declarationToLoc(d),
        }));
        console.log(JSON.stringify({ count: result.length, symbols: result }, null, 2));
    },

    'doc-symbols'(args) {
        const file = args[0];
        if (!file) { console.error('Usage: doc-symbols <file>'); process.exit(1); }
        const store = getStore();
        const { navigation } = createProviders(store);
        const uri = pathToFileUri(path.resolve(file));
        const decls = navigation.getDocumentSymbols(uri);
        const result = decls.map(d => ({
            name: d.name?.name || '', kind: nodeKindName(d), ...declarationToLoc(d),
        }));
        console.log(JSON.stringify({ count: result.length, symbols: result }, null, 2));
    },

    definition(args) {
        const [file, lineStr, charStr] = args;
        if (!file || lineStr === undefined || charStr === undefined) {
            console.error('Usage: definition <file> <line> <character>');
            process.exit(1);
        }
        const line = parseInt(lineStr, 10);
        const character = parseInt(charStr, 10);
        const store = getStore();
        const { definition } = createProviders(store);
        const uri = pathToFileUri(path.resolve(file));
        const sf = store.documents.get(uri);
        if (!sf) { console.error(`File not indexed: ${file}`); process.exit(1); }
        const pos = getPositionOfLineAndCharacter(sf, line, character);
        const links = definition.getDefinitionAt(uri, pos) || [];
        const result = links.map(l => ({
            targetFile: fileUriToPath(l.targetUri || ''),
            startLine: l.targetRange?.start?.line, startCharacter: l.targetRange?.start?.character,
            endLine: l.targetRange?.end?.line, endCharacter: l.targetRange?.end?.character,
        }));
        console.log(JSON.stringify({ count: result.length, definitions: result }, null, 2));
    },

    diagnostics(args) {
        const file = args[0];
        if (!file) { console.error('Usage: diagnostics <file>'); process.exit(1); }
        const store = getStore();
        const { diagnostics } = createProviders(store);
        const uri = pathToFileUri(path.resolve(file));
        const sf = store.documents.get(uri);
        if (!sf) { console.error(`File not indexed: ${file}`); process.exit(1); }
        const diags = diagnostics.provideDiagnostics(uri) || [];
        const result = diags.map(d => ({
            severity: d.severity === 1 ? 'error' : (d.severity === 2 ? 'warning' : 'info'),
            message: d.message,
            line: d.range?.start?.line || 0,
            character: d.range?.start?.character || 0,
            source: d.source || 'galaxy',
        }));
        console.log(JSON.stringify({ count: result.length, diagnostics: result }, null, 2));
    },

    help() {
        console.log(`Galaxy CLI Query Tool

Usage:
  node galaxy-query.mjs index <dir1> [dir2 ...]    Index .galaxy files (must run first)
  node galaxy-query.mjs lookup <symbolName>         Lookup a global symbol by exact name
  node galaxy-query.mjs symbols [query]             Fuzzy-search workspace symbols
  node galaxy-query.mjs doc-symbols <file>          Get top-level declarations in a file
  node galaxy-query.mjs definition <file> <line> <char>  Find definition at position
  node galaxy-query.mjs diagnostics <file>          Get parse/type errors for a file

Cache: ${CACHE_PATH}
Bundle: ${BUNDLE_PATH}

Line and character numbers are 0-based (LSP convention).`);
    },
};

// ── Main ──
const [cmd, ...cmdArgs] = process.argv.slice(2);
const handler = COMMANDS[cmd];
if (!handler) {
    console.error(`Unknown command: ${cmd || '(none)'}`);
    COMMANDS.help();
    process.exit(1);
}
const result = handler(cmdArgs);
if (result instanceof Promise) {
    result.catch(e => { console.error(`Error: ${e.message}`); process.exit(1); });
}
