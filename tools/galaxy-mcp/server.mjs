#!/usr/bin/env node
/**
 * Galaxy MCP Server — provides Galaxy Script code intelligence to AI via MCP.
 *
 * Bridges sc2-lsp's Store + providers to the Model Context Protocol over stdio.
 * Exposes tools: index_workspace, lookup_symbol, workspace_symbols,
 * document_symbols, find_definition, get_diagnostics.
 *
 * Usage: node server.mjs
 * Config: GALAXY_LSP_BUNDLE env var (path to sc2-lsp.mjs, default = sibling reference toolkit)
 */

import { pathToFileURL } from 'node:url';
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as readline from 'node:readline';

// ── Resolve sc2-lsp library bundle path ──
// NOTE: use sc2-lsp-lib.mjs (library mode, exports API only, no side effects).
// The sc2-lsp.mjs bundle auto-starts an LSP connection via src/run.ts, which is
// only suitable for an editor; for MCP use the lib bundle instead.
const DEFAULT_BUNDLE = 'e:/Code/MyMod/SC2VibeTools/sc2-porting-workspace/reference/sc2-galaxy-toolkit/packages/sc2-lsp/dist/sc2-lsp-lib.mjs';
const BUNDLE_PATH = process.env.GALAXY_LSP_BUNDLE || DEFAULT_BUNDLE;

const sc2lsp = await import(pathToFileURL(BUNDLE_PATH).href);
const {
    Store,
    createTextDocument,
    createProvider,
    NavigationProvider,
    DefinitionProvider,
    DiagnosticsProvider,
    getPositionOfLineAndCharacter,
    getLineAndCharacterOfPosition,
    getNodeRange,
    getSourceFileOfNode,
    SyntaxKind,
    SymbolFlags,
    isToken,
    forEachChild,
} = sc2lsp;

// ── Global state ──
const store = new Store();
const navigationProvider = createProvider(NavigationProvider, store);
const definitionProvider = createProvider(DefinitionProvider, store);
const diagnosticsProvider = createProvider(DiagnosticsProvider, store);

let initialized = false;
let indexedCount = 0;

// ── Helpers ──

function fileUriToPath(uri) {
    if (uri.startsWith('file:///')) {
        return decodeURIComponent(uri.slice('file://'.length));
    }
    return uri;
}

function pathToFileUri(p) {
    // Normalize to forward slashes for URI
    let normalized = p.replace(/\\/g, '/');
    if (!normalized.startsWith('/')) {
        normalized = '/' + normalized;
    }
    return 'file://' + encodeURI(normalized);
}

function rangeToObj(range) {
    return {
        startLine: range.start.line,
        startCharacter: range.start.character,
        endLine: range.end.line,
        endCharacter: range.end.character,
    };
}

function symbolKindName(flags) {
    if (typeof flags !== 'number') return 'unknown';
    const parts = [];
    if (typeof SymbolFlags !== 'undefined') {
        // Use the real enum when available; fall back to bit-pattern otherwise.
        const flagNames = [
            ['Function', SymbolFlags.Function],
            ['Struct', SymbolFlags.Struct],
            ['GlobalVariable', SymbolFlags.GlobalVariable],
            ['LocalVariable', SymbolFlags.LocalVariable],
            ['FunctionParameter', SymbolFlags.FunctionParameter],
            ['Property', SymbolFlags.Property],
            ['Typedef', SymbolFlags.Typedef],
            ['Static', SymbolFlags.Static],
            ['Native', SymbolFlags.Native],
        ];
        for (const [name, val] of flagNames) {
            if (typeof val === 'number' && (flags & val) === val && val !== 0) parts.push(name);
        }
        if (parts.length) return parts.join('|');
    }
    // Fallback bit-pattern (kept for older bundles)
    if (flags & 0x02) parts.push('LocalVariable');
    if (flags & 0x04) parts.push('Parameter');
    if (flags & 0x08) parts.push('GlobalVariable');
    if (flags & 0x10) parts.push('Property');
    if (flags & 0x20) parts.push('Function');
    if (flags & 0x40) parts.push('Struct');
    if (flags & 0x80) parts.push('Typedef');
    if (flags & 0x400) parts.push('Static');
    if (flags & 0x800) parts.push('Native');
    return parts.length ? parts.join('|') : 'none';
}

function nodeKindName(node) {
    if (!node || typeof node.kind !== 'number') return 'unknown';
    if (SyntaxKind) {
        for (const [name, val] of Object.entries(SyntaxKind)) {
            if (val === node.kind) return name;
        }
    }
    return String(node.kind);
}

function declarationToLoc(decl) {
    // getSourceFileOfNode walks parents to find the owning SourceFile.
    const sf = typeof getSourceFileOfNode === 'function' ? getSourceFileOfNode(decl) : (decl._sourceFile || decl);
    const range = getNodeRange(decl);
    const fileName = sf ? (sf.fileName || sf.uri || '') : '';
    return {
        file: fileName ? fileUriToPath(fileName) : '',
        line: range.start.line,
        character: range.start.character,
        endLine: range.end.line,
        endCharacter: range.end.character,
        kind: nodeKindName(decl),
    };
}

async function indexDirectory(dir) {
    const errors = [];
    let count = 0;
    const files = await findGalaxyFiles(dir);
    for (const filePath of files) {
        try {
            const text = fs.readFileSync(filePath, 'utf8');
            const uri = pathToFileUri(filePath);
            const doc = createTextDocument(uri, text);
            store.updateDocument(doc);
            count++;
        } catch (e) {
            errors.push(`${filePath}: ${e.message}`);
        }
    }
    return { count, errors };
}

async function findGalaxyFiles(dir) {
    const results = [];
    async function walk(d) {
        let entries;
        try {
            entries = fs.readdirSync(d, { withFileTypes: true });
        } catch {
            return;
        }
        for (const entry of entries) {
            const full = path.join(d, entry.name);
            if (entry.isDirectory()) {
                // Skip node_modules and .git
                if (entry.name === 'node_modules' || entry.name === '.git') continue;
                await walk(full);
            } else if (entry.name.endsWith('.galaxy') || entry.name.endsWith('.galaxya')) {
                results.push(full);
            }
        }
    }
    await walk(dir);
    return results;
}

// ── MCP Tool handlers ──

const TOOL_HANDLERS = {
    async index_workspace(args) {
        const dirs = args.directories || [];
        if (!Array.isArray(dirs) || dirs.length === 0) {
            throw new Error('directories (string[]) is required');
        }
        store.clear();
        indexedCount = 0;
        const allErrors = [];
        for (const dir of dirs) {
            const absDir = path.resolve(dir);
            const r = await indexDirectory(absDir);
            indexedCount += r.count;
            allErrors.push(...r.errors);
        }
        return {
            filesIndexed: indexedCount,
            globalSymbols: countGlobalSymbols(),
            errors: allErrors,
        };
    },

    lookup_symbol(args) {
        const name = args.name;
        if (!name) throw new Error('name (string) is required');
        const sym = store.resolveGlobalSymbol(name);
        if (!sym) {
            return { found: false };
        }
        const decls = (sym.declarations || []).map(declarationToLoc);
        return {
            found: true,
            name: sym.escapedName,
            flags: symbolKindName(sym.flags),
            declarations: decls,
        };
    },

    workspace_symbols(args) {
        const query = args.query || '';
        const decls = navigationProvider.getWorkspaceSymbols(query);
        return decls.map(d => ({
            name: d.name?.name || '',
            kind: nodeKindName(d),
            ...declarationToLoc(d),
        }));
    },

    document_symbols(args) {
        const file = args.file;
        if (!file) throw new Error('file (string) is required');
        const uri = pathToFileUri(path.resolve(file));
        const decls = navigationProvider.getDocumentSymbols(uri);
        return decls.map(d => ({
            name: d.name?.name || '',
            kind: nodeKindName(d),
            ...declarationToLoc(d),
        }));
    },

    find_definition(args) {
        const file = args.file;
        const line = args.line;
        const character = args.character;
        if (!file || typeof line !== 'number' || typeof character !== 'number') {
            throw new Error('file (string), line (number), character (number) are required');
        }
        const uri = pathToFileUri(path.resolve(file));
        const sf = store.documents.get(uri);
        if (!sf) {
            throw new Error(`File not indexed: ${file}. Call index_workspace first.`);
        }
        const pos = getPositionOfLineAndCharacter(sf, line, character);
        const links = definitionProvider.getDefinitionAt(uri, pos);
        if (!links || !links.length) {
            return [];
        }
        return links.map(l => ({
            targetFile: fileUriToPath(l.targetUri || ''),
            ...rangeToObj(l.targetRange || {}),
            ...rangeToObj(l.targetSelectionRange || {}, 'sel'),
        }));
    },

    get_diagnostics(args) {
        const file = args.file;
        if (!file) throw new Error('file (string) is required');
        const uri = pathToFileUri(path.resolve(file));
        const sf = store.documents.get(uri);
        if (!sf) {
            throw new Error(`File not indexed: ${file}. Call index_workspace first.`);
        }
        const diags = diagnosticsProvider.provideDiagnostics(uri) || [];
        return diags.map(d => ({
            severity: d.severity === 1 ? 'error' : (d.severity === 2 ? 'warning' : 'info'),
            message: d.message,
            line: d.range ? d.range.start.line : 0,
            character: d.range ? d.range.start.character : 0,
            source: d.source || 'galaxy',
        }));
    },
};

function countGlobalSymbols() {
    let n = 0;
    for (const doc of store.documents.values()) {
        if (doc.symbol?.members) {
            n += doc.symbol.members.size;
        }
    }
    return n;
}

// ── MCP Tool schemas ──

const TOOLS = [
    {
        name: 'index_workspace',
        description: 'Index all .galaxy files from the given directories. MUST be called before lookup_symbol, find_definition, get_diagnostics, etc. Clears previous index.',
        inputSchema: {
            type: 'object',
            properties: {
                directories: {
                    type: 'array',
                    items: { type: 'string' },
                    description: 'Absolute directory paths to scan recursively for .galaxy files',
                },
            },
            required: ['directories'],
        },
    },
    {
        name: 'lookup_symbol',
        description: 'Look up a global symbol (function, variable, struct, typedef) by exact name. Returns kind, flags, and all declaration locations.',
        inputSchema: {
            type: 'object',
            properties: {
                name: { type: 'string', description: 'Exact symbol name (case-sensitive)' },
            },
            required: ['name'],
        },
    },
    {
        name: 'workspace_symbols',
        description: 'Fuzzy-search all indexed workspace symbols. Returns up to 100 matches with name, kind, file, line, character.',
        inputSchema: {
            type: 'object',
            properties: {
                query: { type: 'string', description: 'Fuzzy search query (case-insensitive)' },
            },
        },
    },
    {
        name: 'document_symbols',
        description: 'Get all top-level declarations (functions, variables, structs) in a specific .galaxy file.',
        inputSchema: {
            type: 'object',
            properties: {
                file: { type: 'string', description: 'Absolute path to the .galaxy file' },
            },
            required: ['file'],
        },
    },
    {
        name: 'find_definition',
        description: 'Find the definition(s) of the symbol at the given 0-based line/character position in a file. Returns target file and range.',
        inputSchema: {
            type: 'object',
            properties: {
                file: { type: 'string', description: 'Absolute path to the .galaxy file' },
                line: { type: 'number', description: '0-based line number' },
                character: { type: 'number', description: '0-based character offset' },
            },
            required: ['file', 'line', 'character'],
        },
    },
    {
        name: 'get_diagnostics',
        description: 'Get parse errors, type errors, and warnings for a .galaxy file. Returns severity, message, line, character.',
        inputSchema: {
            type: 'object',
            properties: {
                file: { type: 'string', description: 'Absolute path to the .galaxy file' },
            },
            required: ['file'],
        },
    },
];

// ── JSON-RPC over stdio ──

const rl = readline.createInterface({ input: process.stdin, terminal: false });

function send(obj) {
    process.stdout.write(JSON.stringify(obj) + '\n');
}

function sendResult(id, result) {
    send({ jsonrpc: '2.0', id, result });
}

function sendError(id, code, message, data) {
    send({ jsonrpc: '2.0', id, error: { code, message, data } });
}

rl.on('line', (line) => {
    let msg;
    try {
        msg = JSON.parse(line);
    } catch {
        return; // ignore non-JSON lines
    }
    if (!msg || msg.jsonrpc !== '2.0' || typeof msg.method !== 'string') return;

    const { id, method, params } = msg;

    switch (method) {
        case 'initialize':
            initialized = true;
            sendResult(id, {
                protocolVersion: '2024-11-05',
                capabilities: {
                    tools: {},
                },
                serverInfo: {
                    name: 'galaxy-lsp',
                    version: '1.0.0',
                },
            });
            break;

        case 'initialized':
            // notification, no response
            break;

        case 'tools/list':
            sendResult(id, { tools: TOOLS });
            break;

        case 'tools/call': {
            const toolName = params?.name;
            const args = params?.arguments || {};
            const handler = TOOL_HANDLERS[toolName];
            if (!handler) {
                sendError(id, -32601, `Unknown tool: ${toolName}`);
                break;
            }
            try {
                const result = handler(args);
                const resolved = result instanceof Promise ? result : Promise.resolve(result);
                resolved.then(r => {
                    sendResult(id, {
                        content: [{ type: 'text', text: JSON.stringify(r, null, 2) }],
                    });
                }).catch(e => {
                    sendResult(id, -32603, `Tool error: ${e.message}`, { stack: e.stack });
                });
            } catch (e) {
                sendResult(id, -32603, `Tool error: ${e.message}`, { stack: e.stack });
            }
            break;
        }

        case 'shutdown':
            sendResult(id, {});
            break;

        case 'exit':
            process.exit(0);
            break;

        default:
            if (id !== undefined) {
                sendError(id, -32601, `Method not found: ${method}`);
            }
    }
});

process.stderr.write('[galaxy-lsp] MCP server ready on stdio\n');
