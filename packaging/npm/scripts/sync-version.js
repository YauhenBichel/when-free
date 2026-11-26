#!/usr/bin/env node
// The npm version is the PyPI version: the launcher starts `uvx when-free==<npm version>`.
//   node packaging/npm/scripts/sync-version.js           write pyproject.toml's version into package.json
//   node packaging/npm/scripts/sync-version.js --check   exit 1 if they differ, change nothing
// release.yml runs it before `npm publish`; tests/test_packaging.py fails if the two differ.
'use strict';

const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..', '..', '..');
const packageFile = path.resolve(__dirname, '..', 'package.json');

function pythonVersion(text) {
  const project = text.split(/^\[project\]\s*$/m)[1];
  const match = project && project.split(/^\[/m)[0].match(/^version\s*=\s*"([^"]+)"/m);
  if (!match) throw new Error('no version under [project] in pyproject.toml');
  return match[1];
}

function main() {
  const version = pythonVersion(fs.readFileSync(path.join(root, 'pyproject.toml'), 'utf8'));
  // npm wants MAJOR.MINOR.PATCH. A Python pre-release (0.6.0rc1) is written differently on npm,
  // so it is refused here instead of being published under a version that uvx cannot find.
  if (!/^\d+\.\d+\.\d+$/.test(version)) {
    console.error(`error: ${version} is not MAJOR.MINOR.PATCH; the npm launcher is only published for final releases`);
    process.exit(1);
  }
  const text = fs.readFileSync(packageFile, 'utf8');
  const current = JSON.parse(text).version;
  if (process.argv.includes('--check')) {
    if (current !== version) {
      console.error(`error: packaging/npm/package.json says ${current}, pyproject.toml says ${version}`);
      process.exit(1);
    }
    console.log(`package.json and pyproject.toml both say ${version}`);
    return;
  }
  if (current !== version) {
    fs.writeFileSync(packageFile, text.replace(/("version":\s*")[^"]+(")/, `$1${version}$2`));
  }
  console.log(`package.json version: ${version}`);
}

if (require.main === module) main();

module.exports = { pythonVersion };
