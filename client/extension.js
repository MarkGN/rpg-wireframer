const path = require('path');
const vscode = require('vscode');
const { LanguageClient, TransportKind } = require('vscode-languageclient/node');

let client;

function activate(context) {
    const serverModule = context.asAbsolutePath(path.join('tools', 'lsp.py'));
    const pythonExecutable = vscode.workspace.getConfiguration('python').get('pythonPath') || 'python3';

    const serverOptions = {
        command: pythonExecutable,
        args: [serverModule],
        transport: TransportKind.stdio
    };

    const clientOptions = {
        documentSelector: [{ scheme: 'file', language: 'yaml' }],
        synchronize: {
            fileEvents: vscode.workspace.createFileSystemWatcher('**/*.yaml')
        }
    };

    client = new LanguageClient(
        'wireframerLSP',
        'Wireframer Language Server',
        serverOptions,
        clientOptions
    );

    client.start();
}

function deactivate() {
    if (!client) {
        return undefined;
    }
    return client.stop();
}

module.exports = {
    activate,
    deactivate
};
