// Tests for the launcher, with Node's own test runner and no dependencies: `npm test`.
// The launcher is started as a separate process with a PATH that holds only stand-ins for
// uvx, uv, pipx and python3, so nothing here touches the real tools or the network.
'use strict';

const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const LAUNCHER = path.resolve(__dirname, '..', 'bin', 'when-free.js');
const { VERSION, SPEC, which, notInstalled } = require(LAUNCHER);
const WINDOWS = process.platform === 'win32';
const posixOnly = WINDOWS ? { skip: 'needs POSIX signals or script stand-ins' } : {};

// One stand-in for every tool. What it does is set by STUB_MODE:
//   record  write its name and arguments to STUB_OUT, exit with STUB_EXIT
//   echo    copy standard input to standard output, byte for byte
//   wait    write "ready" to STUB_OUT, then on a signal write its name there and exit 42
//   die     end itself with SIGTERM
// A stand-in named python answers the launcher's import check (-c) with STUB_IMPORT.
const STUB = String.raw`
const fs = require('node:fs');
const path = require('node:path');
const preload = process.env.STUB_PRELOAD === '1';
const name = path.basename(preload ? process.execPath : process.argv[1]).replace(/\.exe$/i, '');
if (!preload || ['uvx', 'uv', 'pipx'].includes(name)) {
  // As a Node preload (Windows), argv[1] is the first argument, made into a path by Node.
  const args = preload ? [path.basename(process.argv[1] || ''), ...process.argv.slice(2)] : process.argv.slice(2);
  const mode = process.env.STUB_MODE || 'record';
  if (name.startsWith('python') && args.includes('-c')) {
    process.exit(Number(process.env.STUB_IMPORT || 1));
  }
  if (mode === 'record') {
    fs.writeFileSync(process.env.STUB_OUT, JSON.stringify({ name, args }));
    process.exit(Number(process.env.STUB_EXIT || 0));
  }
  if (mode === 'echo') {
    const chunk = Buffer.alloc(65536);
    for (;;) {
      let n;
      try {
        n = fs.readSync(0, chunk, 0, chunk.length, null);
      } catch (error) {
        if (error.code === 'EAGAIN') continue;
        if (error.code === 'EOF') break;
        throw error;
      }
      if (n === 0) break;
      let sent = 0;
      while (sent < n) {
        try {
          sent += fs.writeSync(1, chunk, sent, n - sent);
        } catch (error) {
          if (error.code !== 'EAGAIN') throw error;
        }
      }
    }
    process.exit(0);
  }
  if (mode === 'wait') {
    for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
      process.on(signal, () => {
        fs.writeFileSync(process.env.STUB_OUT, signal);
        process.exit(42);
      });
    }
    fs.writeFileSync(process.env.STUB_OUT, 'ready');
    setInterval(() => {}, 1000);
  }
  if (mode === 'die') process.kill(process.pid, 'SIGTERM');
}
`;

// A temp folder with stand-ins for the named tools; returns the folder.
function fakeBin(t, names) {
  const dir = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'when-free-test-')));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true, maxRetries: 5 }));
  if (WINDOWS) {
    // Only a real .exe can be started without a shell, so the stand-in is Node itself under
    // another name, and the code above is loaded into it with NODE_OPTIONS.
    fs.writeFileSync(path.join(dir, 'stub.js'), STUB);
    for (const name of names) {
      const exe = path.join(dir, name + '.exe');
      try {
        fs.linkSync(process.execPath, exe);
      } catch {
        fs.copyFileSync(process.execPath, exe);
      }
    }
  } else {
    for (const name of names) {
      fs.writeFileSync(path.join(dir, name), `#!${process.execPath}\n${STUB}`, { mode: 0o755 });
    }
  }
  return dir;
}

function launcherEnv(dir, extra = {}) {
  const env = { PATH: dir, STUB_OUT: path.join(dir, 'out.json'), ...extra };
  if (WINDOWS) {
    env.SystemRoot = process.env.SystemRoot;
    env.STUB_PRELOAD = '1';
    env.NODE_OPTIONS = `--require ${path.join(dir, 'stub.js').replace(/\\/g, '/')}`;
  }
  return env;
}

// Start the launcher; resolves with { code, signal, stdout, stderr } (buffers) when it has ended.
function launch(dir, args, { env = {}, input = null, cwd = dir } = {}) {
  const child = spawn(process.execPath, [LAUNCHER, ...args], {
    env: launcherEnv(dir, env),
    cwd,
    stdio: ['pipe', 'pipe', 'pipe'],
  });
  const out = [];
  const err = [];
  child.stdout.on('data', (d) => out.push(d));
  child.stderr.on('data', (d) => err.push(d));
  const done = new Promise((resolve, reject) => {
    child.on('error', reject);
    child.on('close', (code, signal) =>
      resolve({ code, signal, stdout: Buffer.concat(out), stderr: Buffer.concat(err) }));
  });
  if (input !== null) child.stdin.end(input);
  return { child, done };
}

async function run(dir, args, options = {}) {
  return launch(dir, args, { input: '', ...options }).done;
}

const recorded = (dir) => JSON.parse(fs.readFileSync(path.join(dir, 'out.json'), 'utf8'));

async function waitFor(file, text) {
  for (let i = 0; i < 200; i++) {
    try {
      if (fs.readFileSync(file, 'utf8') === text) return;
    } catch {
      // not written yet
    }
    await new Promise((r) => setTimeout(r, 25));
  }
  throw new Error(`timed out waiting for ${text} in ${file}`);
}

test('the version it starts is the version of the npm package', () => {
  assert.equal(VERSION, require('../package.json').version);
  assert.equal(SPEC, `when-free==${VERSION}`);
});

test('uvx comes first', async (t) => {
  const dir = fakeBin(t, ['uvx', 'uv', 'pipx']);
  const result = await run(dir, ['mcp']);
  assert.equal(result.code, 0, result.stderr.toString());
  assert.deepEqual(recorded(dir), { name: 'uvx', args: [SPEC, 'mcp'] });
});

test('without uvx, uv tool run', async (t) => {
  const dir = fakeBin(t, ['uv', 'pipx']);
  const result = await run(dir, ['mcp']);
  assert.equal(result.code, 0, result.stderr.toString());
  assert.deepEqual(recorded(dir), { name: 'uv', args: ['tool', 'run', SPEC, 'mcp'] });
});

test('without uv, pipx run', async (t) => {
  const dir = fakeBin(t, ['pipx']);
  const result = await run(dir, ['mcp']);
  assert.equal(result.code, 0, result.stderr.toString());
  assert.deepEqual(recorded(dir), { name: 'pipx', args: ['run', SPEC, 'mcp'] });
});

test('python3 -m whenfree only when the module is there', posixOnly, async (t) => {
  const dir = fakeBin(t, ['python3']);
  const found = await run(dir, ['mcp'], { env: { STUB_IMPORT: '0' } });
  assert.equal(found.code, 0, found.stderr.toString());
  assert.deepEqual(recorded(dir), { name: 'python3', args: ['-P', '-m', 'whenfree', 'mcp'] });
  assert.equal(found.stderr.length, 0);

  fs.rmSync(path.join(dir, 'out.json'));
  const missing = await run(dir, ['mcp'], { env: { STUB_IMPORT: '1' } });
  assert.equal(missing.code, 127);
  assert.equal(fs.existsSync(path.join(dir, 'out.json')), false);
});

test('a Python with another version of when-free runs, with a warning on stderr', posixOnly, async (t) => {
  const dir = fakeBin(t, ['python3']);
  const result = await run(dir, ['mcp'], { env: { STUB_IMPORT: '3' } });
  assert.equal(result.code, 0);
  assert.equal(recorded(dir).name, 'python3');
  assert.match(result.stderr.toString(), new RegExp(`not version ${VERSION.replace(/\./g, '\\.')}`));
  assert.equal(result.stdout.length, 0);
});

test('nothing installed: one message on stderr with the uv install command, exit 127', async (t) => {
  const dir = fakeBin(t, []);
  const result = await run(dir, ['mcp']);
  assert.equal(result.code, 127);
  assert.equal(result.stdout.length, 0);
  const message = result.stderr.toString();
  assert.equal(message, notInstalled());
  assert.match(message, /astral\.sh\/uv\/install\.(sh|ps1)/);
  assert.match(message, new RegExp(SPEC.replace(/\./g, '\\.')));
});

test('the current folder is not searched, even when PATH says so', posixOnly, async (t) => {
  const dir = fakeBin(t, ['uvx']);
  const result = await run(dir, ['mcp'], { env: { PATH: ':.:bin' }, cwd: dir });
  assert.equal(result.code, 127);
  assert.equal(fs.existsSync(path.join(dir, 'out.json')), false);
});

test('Windows: a .cmd wrapper is not started, only a real program', { skip: !WINDOWS && 'Windows only' }, async (t) => {
  const dir = fakeBin(t, []);
  fs.writeFileSync(path.join(dir, 'uvx.cmd'), '@echo off\r\necho wrapper ran\r\n');
  assert.equal(which('uvx', { Path: dir }), null);
  const result = await run(dir, ['mcp']);
  assert.equal(result.code, 127);
  assert.equal(result.stdout.length, 0);
});

test('arguments arrive unchanged, one by one, and no shell reads them', async (t) => {
  const dir = fakeBin(t, ['uvx']);
  const args = [
    '--message', 'can you do Tuesday at 3?',
    'two words', "it's", '"quoted"', '$(touch pwned)', '`touch pwned`', 'a; touch pwned', 'a && touch pwned',
    'a | touch pwned', '> pwned', 'line one\nline two', '', '--flag=va lue', '*', '~', '$HOME', '%PATH%', '^',
    'back\\slash', 'trailing\\', 'tab\there', 'ünï©ødé', '--', '-x',
  ];
  const result = await run(dir, args);
  assert.equal(result.code, 0, result.stderr.toString());
  assert.deepEqual(recorded(dir), { name: 'uvx', args: [SPEC, ...args] });
  assert.deepEqual(fs.readdirSync(dir).filter((f) => f.includes('pwned')), []);
});

test('the exit code is the child\'s', async (t) => {
  const dir = fakeBin(t, ['uvx']);
  for (const code of [0, 1, 2, 7, 130]) {
    const result = await run(dir, ['x'], { env: { STUB_EXIT: String(code) } });
    assert.equal(result.code, code);
    assert.equal(result.signal, null);
  }
});

test('the launcher itself writes nothing to stdout or stderr', async (t) => {
  const dir = fakeBin(t, ['uvx']);
  const result = await run(dir, ['mcp']);
  assert.equal(result.stdout.length, 0);
  assert.equal(result.stderr.length, 0);
});

for (const signal of ['SIGTERM', 'SIGINT', 'SIGHUP']) {
  test(`${signal} is passed on to the child, and the launcher ends when the child does`, posixOnly, async (t) => {
    const dir = fakeBin(t, ['uvx']);
    const out = path.join(dir, 'out.json');
    const { child, done } = launch(dir, ['mcp'], { env: { STUB_MODE: 'wait' } });
    await waitFor(out, 'ready');
    child.kill(signal);
    const result = await done;
    assert.equal(fs.readFileSync(out, 'utf8'), signal);
    assert.equal(result.code, 42);
  });
}

test('a child ended by a signal ends the launcher the same way', posixOnly, async (t) => {
  const dir = fakeBin(t, ['uvx']);
  const result = await run(dir, ['mcp'], { env: { STUB_MODE: 'die' } });
  assert.equal(result.signal, 'SIGTERM');
});

test('MCP over stdio: 1,000 lines and one 1 MB line come back byte for byte', async (t) => {
  const dir = fakeBin(t, ['uvx']);
  const lines = [];
  for (let id = 1; id <= 1000; id++) {
    lines.push(JSON.stringify({ jsonrpc: '2.0', id, method: 'tools/call', params: { name: 'free_slots', arguments: { message: `Tuesday ${id}? “ünï©ødé” \u0000 \t` } } }));
  }
  lines.push(JSON.stringify({ jsonrpc: '2.0', id: 1001, result: { text: 'x'.repeat(1024 * 1024) } }));
  const input = Buffer.from(lines.join('\n') + '\n', 'utf8');
  assert.ok(input.length > 1024 * 1024);
  const result = await run(dir, ['mcp'], { env: { STUB_MODE: 'echo' }, input });
  assert.equal(result.code, 0, result.stderr.toString());
  assert.equal(result.stderr.length, 0);
  assert.equal(result.stdout.length, input.length);
  assert.ok(result.stdout.equals(input));
});

test('MCP over stdio: each answer arrives before the next request is sent', async (t) => {
  const dir = fakeBin(t, ['uvx']);
  const { child, done } = launch(dir, ['mcp'], { env: { STUB_MODE: 'echo' } });
  let seen = '';
  let wake = () => {};
  child.stdout.on('data', (d) => {
    seen += d.toString();
    wake();
  });
  for (let id = 1; id <= 5; id++) {
    const line = JSON.stringify({ jsonrpc: '2.0', id, method: 'ping' }) + '\n';
    const before = seen.length;
    child.stdin.write(line);
    const deadline = Date.now() + 10000;
    while (seen.length < before + line.length) {
      assert.ok(Date.now() < deadline, 'no answer while stdin is still open: something is buffering');
      await new Promise((r) => {
        wake = r;
        setTimeout(r, 100);
      });
    }
    assert.equal(seen.slice(before), line);
  }
  child.stdin.end();
  const result = await done;
  assert.equal(result.code, 0);
});
