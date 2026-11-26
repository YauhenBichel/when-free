#!/usr/bin/env node
// The npm package when-free is a launcher. It starts the Python tool of the same
// version (`uvx when-free==<version> <arguments>`) and gets out of the way:
//   - the child inherits stdin, stdout and stderr, so MCP over stdio passes untouched;
//   - arguments go as an argv array, never through a shell;
//   - anything the launcher itself says goes to stderr;
//   - SIGINT, SIGTERM and SIGHUP are passed on, and the child's exit code is ours.
// No dependencies, nothing downloaded at install time.
'use strict';

const { spawn, spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const VERSION = require('../package.json').version;
const SPEC = `when-free==${VERSION}`;

// The full path of `name` on PATH, or null. We look it up ourselves, so that
//   - Windows never falls back to the current folder, as its own search does;
//   - only real programs are taken on Windows (.exe, .com): a .cmd or .bat can only be
//     started through cmd.exe, which would read the arguments as shell text.
// Empty and relative PATH entries are skipped: they mean "whatever folder I am in".
function which(name, env = process.env, platform = process.platform) {
  const win = platform === 'win32';
  const p = win ? path.win32 : path.posix;
  const pathKey = win ? Object.keys(env).find((k) => k.toUpperCase() === 'PATH') : 'PATH';
  const dirs = String((pathKey && env[pathKey]) || '').split(p.delimiter);
  const extensions = win ? ['.exe', '.com'] : [''];
  for (const raw of dirs) {
    const dir = win ? raw.replace(/^"(.*)"$/, '$1') : raw;
    if (!dir || !p.isAbsolute(dir)) continue;
    for (const ext of extensions) {
      const file = p.join(dir, name + ext);
      try {
        if (!fs.statSync(file).isFile()) continue;
        if (!win) fs.accessSync(file, fs.constants.X_OK);
        return file;
      } catch {
        // not here; keep looking
      }
    }
  }
  return null;
}

// -P keeps the current folder off sys.path, so a folder named whenfree in a project cannot
// be started in place of the installed tool. A Python too old for -P (before 3.11) is too
// old for when-free and fails this check, which is what we want.
const PYTHON_CHECK =
  'import sys, whenfree; sys.exit(0 if whenfree.__version__ == sys.argv[1] else 3)';

function pythonWithModule(env, platform, warn) {
  for (const name of ['python3', 'python']) {
    const python = which(name, env, platform);
    if (!python) continue;
    const check = spawnSync(python, ['-P', '-c', PYTHON_CHECK, VERSION], {
      stdio: 'ignore',
      shell: false,
      windowsHide: true,
      timeout: 20000,
    });
    if (check.status === 0) return python;
    if (check.status === 3) {
      warn(`when-free: uv and pipx were not found; using the when-free installed for ${python}, which is not version ${VERSION}.`);
      return python;
    }
  }
  return null;
}

// What to run, in order of preference; null when nothing can run when-free.
function resolve(args, env = process.env, platform = process.platform, warn = () => {}) {
  const uvx = which('uvx', env, platform);
  if (uvx) return { command: uvx, args: [SPEC, ...args] };
  const uv = which('uv', env, platform);
  if (uv) return { command: uv, args: ['tool', 'run', SPEC, ...args] };
  const pipx = which('pipx', env, platform);
  if (pipx) return { command: pipx, args: ['run', SPEC, ...args] };
  const python = pythonWithModule(env, platform, warn);
  if (python) return { command: python, args: ['-P', '-m', 'whenfree', ...args] };
  return null;
}

function notInstalled(platform = process.platform) {
  const install =
    platform === 'win32'
      ? 'powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"'
      : 'curl -LsSf https://astral.sh/uv/install.sh | sh';
  return (
    `when-free: this npm package starts the Python tool ${SPEC} with uv, and uvx was not found on PATH ` +
    `(nor uv, pipx, or a Python with when-free installed). Install uv, then run this again:\n  ${install}\n`
  );
}

function main() {
  const say = (line) => process.stderr.write(line.endsWith('\n') ? line : line + '\n');
  const found = resolve(process.argv.slice(2), process.env, process.platform, say);
  if (!found) {
    say(notInstalled());
    process.exitCode = 127;
    return;
  }

  const child = spawn(found.command, found.args, { stdio: 'inherit', shell: false, windowsHide: true });

  const signals = ['SIGINT', 'SIGTERM', 'SIGHUP'];
  const forward = {};
  for (const signal of signals) {
    forward[signal] = () => {
      try {
        child.kill(signal);
      } catch {
        // the child is already gone; its exit event ends us
      }
    };
    process.on(signal, forward[signal]);
  }

  child.on('error', (error) => {
    say(`when-free: could not start ${found.command}: ${error.message}`);
    process.exit(error.code === 'ENOENT' ? 127 : 126);
  });

  child.on('exit', (code, signal) => {
    if (signal) {
      // End the way the child ended, so whoever started us sees the same thing.
      for (const name of signals) process.removeListener(name, forward[name]);
      try {
        process.kill(process.pid, signal);
      } catch {
        // a signal this platform cannot send: fall through to the exit code
      }
      const number = os.constants.signals[signal] || 0;
      setTimeout(() => process.exit(128 + number), 500);
      return;
    }
    process.exit(code === null ? 1 : code);
  });
}

if (require.main === module) main();

module.exports = { VERSION, SPEC, which, resolve, notInstalled };
