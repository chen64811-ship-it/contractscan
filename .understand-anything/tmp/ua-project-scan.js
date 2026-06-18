#!/usr/bin/env node
/**
 * Project scanner — discovers all project files, detects languages/frameworks,
 * counts lines, estimates complexity, resolves imports.
 *
 * Usage: node ua-project-scan.js <project-root> <output-json-path>
 */

const fs = require('fs');
const path = require('path');
const { execSync, execFileSync } = require('child_process');

// ─── Helpers ───────────────────────────────────────────────────────

function logErr(msg) {
  process.stderr.write(msg + '\n');
}

function readFileIfExists(filePath) {
  try {
    return fs.readFileSync(filePath, 'utf-8');
  } catch {
    return null;
  }
}

function parseJSONSafe(filePath) {
  const content = readFileIfExists(filePath);
  if (!content) return null;
  try {
    return JSON.parse(content);
  } catch {
    return null;
  }
}

function parseTOMLSafe(filePath) {
  const content = readFileIfExists(filePath);
  if (!content) return null;
  // Very simple TOML parser for [dependencies] and [package] sections only
  const result = { dependencies: {}, devDependencies: {}, package: {}, tool: {} };
  const lines = content.split('\n');
  let section = null;
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const sectionMatch = trimmed.match(/^\[(.+?)\]$/);
    if (sectionMatch) {
      section = sectionMatch[1];
      continue;
    }
    const kvMatch = trimmed.match(/^(.+?)\s*=\s*(.+)$/);
    if (kvMatch && section) {
      const key = kvMatch[1].trim().replace(/^"(.*)"$/, '$1').replace(/^'(.*)'$/, '$1');
      const val = kvMatch[2].trim().replace(/^"(.*)"$/, '$1').replace(/^'(.*)'$/, '$1');
      if (section === 'dependencies' || section === 'dev-dependencies' || section.startsWith('dependencies') || section.startsWith('dev-dependencies')) {
        result.dependencies[key] = val;
      } else if (section === 'package') {
        result.package[key] = val;
      } else if (section.startsWith('tool.')) {
        const toolKey = section.replace(/^tool\./, '');
        if (!result.tool[toolKey]) result.tool[toolKey] = {};
        result.tool[toolKey][key] = val;
      }
    }
  }
  return result;
}

// ─── Step 1: File Discovery ────────────────────────────────────────

function discoverFiles(projectRoot) {
  // Try git ls-files first
  try {
    const output = execSync('git ls-files', { cwd: projectRoot, encoding: 'utf-8', stdio: ['pipe', 'pipe', 'pipe'] });
    if (output.trim()) {
      const files = output.trim().split('\n').filter(Boolean);
      logErr(`[discover] git ls-files: ${files.length} files`);
      return files;
    }
  } catch {
    // Not a git repo or git not available, fall through
  }

  // Fall back to recursive file listing
  const files = [];
  function walk(dir, relPath) {
    const entries = fs.readdirSync(dir, { withFileTypes: true });
    for (const entry of entries) {
      if (entry.isDirectory()) {
        walk(path.join(dir, entry.name), relPath + entry.name + '/');
      } else if (entry.isFile()) {
        files.push(relPath + entry.name);
      }
    }
  }
  walk(projectRoot, '');
  // Convert to forward slashes for consistency
  const normalized = files.map(f => f.replace(/\\/g, '/')).sort();
  logErr(`[discover] find walk: ${normalized.length} files`);
  return normalized;
}

// ─── Step 2: Exclusion Filtering ───────────────────────────────────

function defaultExclude(filePath) {
  // Check for dependency directories
  const dirs = filePath.split('/');
  for (const d of dirs) {
    if (['node_modules', '.git', 'vendor', 'venv', '.venv', '__pycache__'].includes(d)) return true;
    // Build output dirs — match full directory segments only
    if (['dist', 'build', 'out', 'coverage', '.next', '.cache', '.turbo', 'target', 'obj'].includes(d) && d !== 'buildSrc') return true;
  }

  // Lock files
  if (filePath.endsWith('.lock') || filePath.endsWith('package-lock.json') || filePath.endsWith('yarn.lock') || filePath.endsWith('pnpm-lock.yaml')) return true;

  // Binary/asset files
  if (/\.(png|jpg|jpeg|gif|svg|ico|woff|woff2|ttf|eot|mp3|mp4|pdf|zip|tar|gz)$/i.test(filePath)) return true;

  // Generated files
  if (/\.min\.(js|css)$/i.test(filePath)) return true;
  if (/\.map$/i.test(filePath)) return true;
  if (/\.generated\./i.test(filePath)) return true;

  // IDE/editor config
  if (dirs.includes('.idea') || dirs.includes('.vscode')) return true;

  // Misc non-source
  const basename = path.basename(filePath);
  if (basename === 'LICENSE') return true;
  if (basename === '.gitignore') return true;
  if (basename === '.editorconfig') return true;
  if (basename.startsWith('.prettierrc')) return true;
  if (basename.startsWith('.eslintrc')) return true;
  if (filePath.endsWith('.log')) return true;

  return false;
}

// Check for .understandignore files
const UA_IGNORE_1 = '.understand-anything/.understandignore';
const UA_IGNORE_2 = '.understandignore';

function hasCustomIgnore(runDir) {
  return fs.existsSync(path.join(runDir, UA_IGNORE_1)) || fs.existsSync(path.join(runDir, UA_IGNORE_2));
}

function filterFiles(allFiles, projectRoot) {
  // Step 2: apply hardcoded defaults
  let filtered = allFiles.filter(f => !defaultExclude(f));

  const baselineCount = filtered.length;
  const removedByDefault = allFiles.length - baselineCount;

  // Step 2.5: .understandignore (if present)
  const ignore1 = path.join(projectRoot, UA_IGNORE_1);
  const ignore2 = path.join(projectRoot, UA_IGNORE_2);

  let ignoreFileContent = '';
  if (fs.existsSync(ignore1)) ignoreFileContent += fs.readFileSync(ignore1, 'utf-8') + '\n';
  if (fs.existsSync(ignore2)) ignoreFileContent += fs.readFileSync(ignore2, 'utf-8') + '\n';

  let filteredByIgnore = 0;
  if (ignoreFileContent.trim()) {
    // Parse .understandignore patterns (that are NOT commented out)
    const patterns = [];
    for (const line of ignoreFileContent.split('\n')) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith('#')) continue;
      // Check for negation patterns
      patterns.push({ pattern: trimmed, negate: trimmed.startsWith('!') });
    }

    if (patterns.length > 0) {
      const afterCustom = [];
      for (const f of filtered) {
        let keep = true;
        for (const { pattern: rawPat, negate } of patterns) {
          let pat = rawPat;
          if (negate) pat = pat.slice(1); // remove leading !
          // Simple glob matching (handle * and **)
          const regex = globToRegex(pat);
          const match = regex.test(f);
          if (negate && match) {
            keep = true; // force-include
          } else if (!negate && match) {
            keep = false;
          }
        }
        if (keep) {
          afterCustom.push(f);
        } else {
          filteredByIgnore++;
        }
      }
      // Only count additional removals beyond defaults
      filteredByIgnore = Math.max(0, filteredByIgnore);
      filtered = afterCustom;
    }
  }

  return { files: filtered, filteredByIgnore, baselineCount };
}

function globToRegex(pat) {
  // Convert .gitignore-style glob to regex
  let r = pat
    .replace(/[.+^${}()|[\]\\]/g, '\\$&') // escape special regex chars
    .replace(/\*\*\//g, '(.*\/)?')  // **/ matches any path prefix
    .replace(/\*/g, '[^/]*')        // * matches anything except /
    .replace(/\?/g, '.');           // ? matches single char
  if (pat.endsWith('/')) {
    r += '.*'; // directory match
  }
  return new RegExp('^' + r + '$');
}

// ─── Step 3: Language Detection ────────────────────────────────────

const EXT_TO_LANG = {
  '.ts': 'typescript', '.tsx': 'typescript',
  '.js': 'javascript', '.jsx': 'javascript', '.mjs': 'javascript', '.cjs': 'javascript',
  '.py': 'python',
  '.go': 'go',
  '.rs': 'rust',
  '.java': 'java',
  '.rb': 'ruby',
  '.cpp': 'cpp', '.cc': 'cpp', '.cxx': 'cpp', '.hpp': 'cpp', '.hh': 'cpp', '.hxx': 'cpp',
  '.h': 'c',
  '.c': 'c',
  '.cs': 'csharp',
  '.swift': 'swift',
  '.kt': 'kotlin', '.kts': 'kotlin',
  '.php': 'php',
  '.vue': 'vue',
  '.svelte': 'svelte',
  '.sh': 'shell', '.bash': 'shell',
  '.ps1': 'powershell',
  '.bat': 'batch', '.cmd': 'batch',
  '.md': 'markdown', '.rst': 'markdown',
  '.yaml': 'yaml', '.yml': 'yaml',
  '.json': 'json',
  '.jsonc': 'jsonc',
  '.toml': 'toml',
  '.sql': 'sql',
  '.graphql': 'graphql', '.gql': 'graphql',
  '.proto': 'protobuf',
  '.tf': 'terraform', '.tfvars': 'terraform',
  '.html': 'html', '.htm': 'html',
  '.css': 'css', '.scss': 'css', '.sass': 'css', '.less': 'css',
  '.xml': 'xml',
  '.cfg': 'config', '.ini': 'config', '.env': 'config',
  '.prisma': 'prisma',
  '.csv': 'csv',
};

const NO_EXT_LANG = {
  'Dockerfile': 'dockerfile',
  'Makefile': 'makefile',
  'Jenkinsfile': 'jenkinsfile',
  'Procfile': 'procfile',
  'Vagrantfile': 'vagrantfile',
};

function detectLanguage(filePath) {
  const basename = path.basename(filePath);
  const ext = path.extname(filePath).toLowerCase();

  // Special-case known config files with unusual extensions
  if (basename === '.env.example') return 'config';
  if (basename === '.dockerignore' || basename === '.gitignore') return 'config';
  if (basename === 'requirements.txt' || basename === 'Pipfile' || basename === 'setup.cfg' || basename === 'setup.py') return 'config';

  if (ext && EXT_TO_LANG[ext]) return EXT_TO_LANG[ext];
  if (NO_EXT_LANG[basename]) return NO_EXT_LANG[basename];
  // Dockerfile variants
  if (basename.startsWith('Dockerfile')) return 'dockerfile';
  if (ext) return ext.slice(1); // fallback: extension without dot
  return 'unknown';
}

// ─── Step 4: File Category Detection ───────────────────────────────

function detectCategory(filePath) {
  const basename = path.basename(filePath);
  const ext = path.extname(filePath).toLowerCase();
  const dirs = filePath.split('/');

  // Priority order — first match wins

  // docs
  if (ext === '.md' || ext === '.rst') return 'docs';
  // .txt files are docs UNLESS they are well-known config files
  if (ext === '.txt' && basename !== 'LICENSE' && basename !== 'requirements.txt') return 'docs';

  // infra
  if (basename.startsWith('Dockerfile') || basename.startsWith('docker-compose')) return 'infra';
  if (basename === '.dockerignore') return 'infra';
  if (ext === '.tf' || ext === '.tfvars') return 'infra';
  if (basename === 'Makefile' || basename === 'Jenkinsfile' || basename === 'Procfile' || basename === 'Vagrantfile') return 'infra';
  if (filePath.startsWith('.github/workflows/')) return 'infra';
  if (basename === '.gitlab-ci.yml') return 'infra';
  if (filePath.startsWith('.circleci/')) return 'infra';
  if (/(\.k8s\.yaml|\.k8s\.yml)$/i.test(filePath) || dirs.includes('k8s') || dirs.includes('kubernetes')) return 'infra';

  // data
  if (ext === '.sql' || ext === '.graphql' || ext === '.gql' || ext === '.proto' || ext === '.prisma' || ext === '.csv') return 'data';
  if (basename.endsWith('.schema.json')) return 'data';

  // script
  if (ext === '.sh' || ext === '.bash' || ext === '.ps1' || ext === '.bat') return 'script';

  // markup
  if (ext === '.html' || ext === '.htm' || ext === '.css' || ext === '.scss' || ext === '.sass' || ext === '.less') return 'markup';

  // config
  if (ext === '.yaml' || ext === '.yml' || ext === '.json' || ext === '.jsonc' || ext === '.toml') return 'config';
  if (ext === '.xml' || ext === '.cfg' || ext === '.ini' || ext === '.env') return 'config';
  if (basename === 'tsconfig.json' || basename === 'package.json' || basename === 'pyproject.toml' || basename === 'Cargo.toml' || basename === 'go.mod') return 'config';
  if (basename === 'requirements.txt' || basename === 'Pipfile' || basename === 'setup.cfg') return 'config';
  if (basename === '.env.example') return 'config';
  if (basename === '.dockerignore') return 'infra'; // already handled above

  // Everything else is code
  return 'code';
}

// ─── Step 5: Line Counting ─────────────────────────────────────────

function countLines(projectRoot, files) {
  const result = {};
  if (files.length === 0) return result;

  if (files.length < 500) {
    // Count one by one using wc
    for (const f of files) {
      try {
        const absPath = path.join(projectRoot, f);
        if (!fs.existsSync(absPath)) { result[f] = 0; continue; }
        const output = execFileSync('wc', ['-l', absPath], { encoding: 'utf-8', stdio: ['pipe', 'pipe', 'pipe'] });
        const match = output.match(/^(\d+)/);
        result[f] = match ? parseInt(match[1], 10) : 0;
      } catch {
        // Fallback: count newlines manually
        try {
          const content = fs.readFileSync(path.join(projectRoot, f), 'utf-8');
          result[f] = content.split('\n').length;
        } catch {
          result[f] = 0;
        }
      }
    }
  } else {
    // Batch wc calls — 100 files per invocation
    const batchSize = 100;
    for (let i = 0; i < files.length; i += batchSize) {
      const batch = files.slice(i, i + batchSize);
      const args = batch.map(f => path.join(projectRoot, f));
      try {
        const output = execFileSync('wc', ['-l', ...args], { encoding: 'utf-8', stdio: ['pipe', 'pipe', 'pipe'] });
        const lines = output.trim().split('\n');
        for (let j = 0; j < batch.length; j++) {
          const match = (lines[j] || '').match(/^\s*(\d+)/);
          result[batch[j]] = match ? parseInt(match[1], 10) : 0;
        }
      } catch {
        // Fallback for batch
        for (const f of batch) {
          try {
            const content = fs.readFileSync(path.join(projectRoot, f), 'utf-8');
            result[f] = content.split('\n').length;
          } catch { result[f] = 0; }
        }
      }
    }
  }
  return result;
}

// ─── Step 6: Framework Detection ────────────────────────────────────

function detectFrameworks(projectRoot, files, allFilePaths) {
  const frameworks = new Set();

  // Check package.json
  const pkgJson = parseJSONSafe(path.join(projectRoot, 'package.json'));
  if (pkgJson) {
    const deps = { ...(pkgJson.dependencies || {}), ...(pkgJson.devDependencies || {}) };
    const depNames = Object.keys(deps);
    const jsFrameworks = ['react', 'vue', 'svelte', '@angular/core', 'express', 'fastify', 'koa',
      'next', 'nuxt', 'vite', 'vitest', 'jest', 'mocha', 'tailwindcss', 'prisma', 'typeorm',
      'sequelize', 'mongoose', 'redux', 'zustand', 'mobx'];
    for (const fw of jsFrameworks) {
      if (depNames.includes(fw)) frameworks.add(fw);
    }
  }

  // Check tsconfig.json
  if (files.some(f => f.endsWith('tsconfig.json'))) {
    frameworks.add('TypeScript');
  }

  // Check requirements.txt
  const reqTxt = files.find(f => f.endsWith('requirements.txt'));
  if (reqTxt) {
    const content = readFileIfExists(path.join(projectRoot, reqTxt));
    if (content) {
      const pythonFrameworks = ['django', 'djangorestframework', 'fastapi', 'flask', 'sqlalchemy',
        'alembic', 'celery', 'pydantic', 'uvicorn', 'gunicorn', 'aiohttp', 'tornado', 'starlette',
        'pytest', 'hypothesis', 'channels', 'paddleocr', 'pymupdf', 'pdfminer', 'openai'];
      const lines = content.split('\n');
      for (const line of lines) {
        const pkgName = line.split(/[=<>[;~!#]/)[0].trim().toLowerCase();
        for (const fw of pythonFrameworks) {
          if (pkgName === fw) frameworks.add(fw.charAt(0).toUpperCase() + fw.slice(1));
        }
      }
    }
  }

  // Check pyproject.toml
  const pyproj = files.find(f => f.endsWith('pyproject.toml'));
  if (pyproj) {
    const toml = parseTOMLSafe(path.join(projectRoot, pyproj));
    if (toml) {
      const pyDeps = Object.keys(toml.dependencies || {});
      const pyFrameworks = ['django', 'djangorestframework', 'fastapi', 'flask', 'sqlalchemy',
        'alembic', 'celery', 'pydantic', 'uvicorn', 'gunicorn', 'aiohttp', 'tornado', 'starlette',
        'pytest', 'hypothesis', 'channels'];
      for (const dep of pyDeps) {
        const lower = dep.toLowerCase();
        if (pyFrameworks.includes(lower)) frameworks.add(lower.charAt(0).toUpperCase() + lower.slice(1));
      }
      if (toml.tool && toml.tool.pytest) frameworks.add('Pytest');
      if (toml.tool && toml.tool.django) frameworks.add('Django');
    }
  }

  // Check Gemfile
  if (files.some(f => f.endsWith('Gemfile'))) {
    frameworks.add('Ruby');
  }

  // Check go.mod
  const goMod = files.find(f => f.endsWith('go.mod'));
  if (goMod) {
    frameworks.add('Go');
  }

  // Check Cargo.toml
  const cargo = files.find(f => f.endsWith('Cargo.toml'));
  if (cargo) {
    frameworks.add('Rust');
  }

  // Infrastructure tooling detection by file presence
  const fileSet = new Set(allFilePaths);
  if (allFilePaths.some(f => path.basename(f) === 'Dockerfile')) frameworks.add('Docker');
  if (allFilePaths.some(f => /^docker-compose\.(yml|yaml)$/.test(path.basename(f)))) frameworks.add('Docker Compose');
  if (allFilePaths.some(f => f.endsWith('.tf'))) frameworks.add('Terraform');
  if (allFilePaths.some(f => f.startsWith('.github/workflows/') && f.endsWith('.yml'))) frameworks.add('GitHub Actions');
  if (allFilePaths.some(f => f.includes('.gitlab-ci.yml'))) frameworks.add('GitLab CI');
  if (allFilePaths.some(f => path.basename(f) === 'Jenkinsfile')) frameworks.add('Jenkins');

  return [...frameworks].sort();
}

// ─── Step 7: Complexity ────────────────────────────────────────────

function estimateComplexity(totalFiles) {
  if (totalFiles <= 30) return 'small';
  if (totalFiles <= 150) return 'moderate';
  if (totalFiles <= 500) return 'large';
  return 'very-large';
}

// ─── Step 8: Project Name ──────────────────────────────────────────

function detectProjectName(projectRoot, files) {
  // 1. package.json name
  const pkgJson = parseJSONSafe(path.join(projectRoot, 'package.json'));
  if (pkgJson && pkgJson.name) return pkgJson.name;

  // 2. Cargo.toml package.name
  const cargoFile = path.join(projectRoot, 'Cargo.toml');
  const cargo = parseTOMLSafe(cargoFile);
  if (cargo && cargo.package && cargo.package.name) return cargo.package.name;

  // 3. go.mod module path (last segment)
  const goMod = readFileIfExists(path.join(projectRoot, 'go.mod'));
  if (goMod) {
    const match = goMod.match(/^module\s+(.+)/m);
    if (match) {
      const parts = match[1].split('/');
      return parts[parts.length - 1];
    }
  }

  // 4. pyproject.toml
  const pyproj = parseTOMLSafe(path.join(projectRoot, 'pyproject.toml'));
  if (pyproj) {
    if (pyproj.package && pyproj.package.name) return pyproj.package.name;
    if (pyproj.tool && pyproj.tool.poetry && pyproj.tool.poetry.name) return pyproj.tool.poetry.name;
  }

  // 5. Directory name
  return path.basename(projectRoot);
}

// ─── Step 9: Import Resolution ─────────────────────────────────────

function resolveImports(projectRoot, files) {
  const importMap = {};
  const fileSet = new Set(files.map(f => f.filePath));

  for (const f of files) {
    const fp = f.filePath;
    if (f.fileCategory !== 'code') {
      importMap[fp] = [];
      continue;
    }
    const resolved = [];
    const ext = path.extname(fp).toLowerCase();
    const dir = path.dirname(fp);

    if (ext === '.py') {
      // Python imports
      const content = readFileIfExists(path.join(projectRoot, fp));
      if (!content) { importMap[fp] = []; continue; }

      // Relative imports: from .x import y, from ..x import y
      // Use [ \t] instead of \s to avoid matching newlines
      const relImportRe = /from[ \t]+(\.+[\w.]*)[ \t]+import[ \t]+/g;
      let match;
      while ((match = relImportRe.exec(content)) !== null) {
        const relPath = match[1];
        const dots = relPath.match(/^\.+/)[0];
        const modPath = relPath.slice(dots.length);
        let baseDir = dir;
        for (let i = 1; i < dots.length; i++) baseDir = path.dirname(baseDir);
        const resolvedMod = modPath ? path.join(baseDir, modPath.replace(/\./g, '/')) : baseDir;
        // Try .py and __init__.py
        const candidates = [resolvedMod + '.py', resolvedMod + '/__init__.py'];
        for (const c of candidates) {
          const normalized = c.replace(/\\/g, '/');
          if (fileSet.has(normalized)) resolved.push(normalized);
        }
      }

      // Absolute imports: import a.b.c, from a.b.c import x
      // Python resolves these against sys.path, which typically includes:
      // - the project root
      // - the directory containing the importing file (when added via sys.path.insert)
      // - common source roots (src/, lib/, etc.)
      // We try multiple source roots to find matches.
      const pythonSourceRoots = new Set();
      pythonSourceRoots.add(''); // project root
      // Add the importing file's directory and its ancestors
      let d = dir;
      while (d && d !== '.') {
        pythonSourceRoots.add(d);
        d = path.dirname(d);
      }
      pythonSourceRoots.add(dir); // the file's own directory

      // Use [ \t] instead of \s to avoid matching newlines inside character classes
      const absImportRe = /(?:^|\n)[ \t]*(?:import[ \t]+([\w.]+)|from[ \t]+([\w.]+)[ \t]+import[ \t]+([\w, \t*()]+))/g;
      while ((match = absImportRe.exec(content)) !== null) {
        const modPath = match[1] || match[2];
        const importedNames = match[3] ? match[3].replace(/[()]/g, '').split(',').map(s => s.trim()).filter(Boolean) : [];
        if (!modPath) continue;
        const filePath_ = modPath.replace(/\./g, '/');

        let found = false;
        // Try every source root
        for (const root of pythonSourceRoots) {
          if (found && importedNames.length === 0) break;
          const prefixed = root ? root + '/' + filePath_ : filePath_;
          const candidates = [prefixed + '.py', prefixed + '/__init__.py'];
          for (const c of candidates) {
            const normalized = c.replace(/\\/g, '/');
            if (fileSet.has(normalized)) {
              resolved.push(normalized);
              found = true;
              // Break candidate loop but continue for other roots if submodule probes needed
              break;
            }
          }
          // For "from a.b.c import x": if a/b/c matched as __init__.py (package), probe submodules
          const pkgInit = prefixed + '/__init__.py';
          if (fileSet.has(pkgInit) && importedNames.length > 0) {
            for (const name of importedNames) {
              if (name === '*') continue;
              const subCandidates = [prefixed + '/' + name + '.py', prefixed + '/' + name + '/__init__.py'];
              for (const sc of subCandidates) {
                const normalized = sc.replace(/\\/g, '/');
                if (fileSet.has(normalized)) resolved.push(normalized);
              }
            }
          }
        }
      }
    } else if (['.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs'].includes(ext)) {
      // TypeScript/JavaScript imports
      const content = readFileIfExists(path.join(projectRoot, fp));
      if (!content) { importMap[fp] = []; continue; }

      // Read tsconfig for path aliases
      const tsconfigPath = path.join(projectRoot, 'tsconfig.json');
      let aliases = {};
      let baseUrl = '.';
      if (fs.existsSync(tsconfigPath)) {
        const tsconfig = parseJSONSafe(tsconfigPath);
        if (tsconfig && tsconfig.compilerOptions) {
          baseUrl = tsconfig.compilerOptions.baseUrl || '.';
          const paths = tsconfig.compilerOptions.paths || {};
          for (const [alias, targets] of Object.entries(paths)) {
            const aliasClean = alias.replace(/\/\*$/, '');
            const target = Array.isArray(targets) ? targets[0].replace(/\/\*$/, '') : targets.replace(/\/\*$/, '');
            aliases[aliasClean] = path.join(baseUrl, target).replace(/\\/g, '/');
          }
        }
      }

      // Relative imports
      const relRe = /(?:import\s+.*?\s+from\s+['"](\.\.?\/[^'"]+)['"]|require\s*\(\s*['"](\.\.?\/[^'"]+)['"]\s*\))/g;
      while ((match = relRe.exec(content)) !== null) {
        const importPath = match[1] || match[2];
        const absImport = path.join(dir, importPath).replace(/\\/g, '/');
        // Try extension variants
        const exts = ['.ts', '.tsx', '.js', '.jsx', '/index.ts', '/index.js', '/index.tsx', '/index.jsx'];
        for (const e of exts) {
          const candidate = absImport + e;
          if (fileSet.has(candidate)) { resolved.push(candidate); break; }
        }
      }

      // Alias imports
      const aliasRe = /(?:import\s+.*?\s+from\s+['"]([^'"]+)['"]|require\s*\(\s*['"]([^'"]+)['"]\s*\))/g;
      while ((match = aliasRe.exec(content)) !== null) {
        const importPath = match[1] || match[2];
        if (importPath.startsWith('.')) continue; // already handled above
        for (const [alias, aliasTarget] of Object.entries(aliases)) {
          if (importPath.startsWith(alias)) {
            const rest = importPath.slice(alias.length);
            const candidate = (aliasTarget + rest).replace(/\\/g, '/');
            const exts = ['.ts', '.tsx', '.js', '.jsx', '/index.ts', '/index.js', '/index.tsx', '/index.jsx'];
            for (const e of exts) {
              const withExt = candidate + e;
              if (fileSet.has(withExt)) { resolved.push(withExt); break; }
            }
          }
        }
      }
    } else if (ext === '.go') {
      // Go imports
      const content = readFileIfExists(path.join(projectRoot, fp));
      if (!content) { importMap[fp] = []; continue; }
      const goModFile = files.find(f => f.filePath.endsWith('go.mod'));
      const goModPath = goModFile ? goModFile.filePath : null;
      const modPathName = goModPath ? readModulePath(path.join(projectRoot, goModPath)) : '';
      if (modPathName) {
        const importRe = /"([^"]+)"/g;
        while ((match = importRe.exec(content)) !== null) {
          const imp = match[1];
          if (imp.startsWith(modPathName)) {
            const rel = imp.slice(modPathName.length);
            const candidate = (rel).replace(/\\/g, '/') + '.go';
            // Also try without leading /
            const candidate2 = candidate.replace(/^\//, '');
            if (fileSet.has(candidate2)) resolved.push(candidate2);
          }
        }
      }
    } else if (ext === '.rs') {
      // Rust crate/super imports
      const content = readFileIfExists(path.join(projectRoot, fp));
      if (!content) { importMap[fp] = []; continue; }
      // mod x
      const modRe = /^\s*mod\s+(\w+)\s*;/gm;
      while ((match = modRe.exec(content)) !== null) {
        const modName = match[1];
        const candidate = path.join(dir, modName + '.rs').replace(/\\/g, '/');
        if (fileSet.has(candidate)) resolved.push(candidate);
      }
      // use crate::
      const crateRe = /use\s+crate::([\w:]+)/g;
      while ((match = crateRe.exec(content)) !== null) {
        const cratePath = match[1].replace(/::/g, '/');
        const candidate = 'src/' + cratePath + '.rs';
        if (fileSet.has(candidate)) resolved.push(candidate);
      }
      // use super::
      const superRe = /use\s+super::([\w:]+)/g;
      while ((match = superRe.exec(content)) !== null) {
        const superPath = match[1].replace(/::/g, '/');
        const parent = path.dirname(dir);
        const candidate = path.join(parent, superPath + '.rs').replace(/\\/g, '/');
        if (fileSet.has(candidate)) resolved.push(candidate);
      }
    } else if (['.cpp', '.cc', '.cxx', '.c', '.h', '.hpp', '.hh'].includes(ext)) {
      // C/C++ includes
      const content = readFileIfExists(path.join(projectRoot, fp));
      if (!content) { importMap[fp] = []; continue; }
      // #include "foo.h" and #include <foo.h>
      const includeRe = /#include\s+["<]([^">]+)[">]/g;
      while ((match = includeRe.exec(content)) !== null) {
        const incPath = match[1];
        const candidates = [
          path.join(dir, incPath).replace(/\\/g, '/'),          // relative to includer
          'include/' + incPath,                                  // include/ dir
          'src/' + incPath,                                     // src/ dir
          incPath,                                              // bare path
        ];
        for (const c of candidates) {
          if (fileSet.has(c)) { resolved.push(c); break; }
          // Also try with common header extensions
          for (const he of ['.h', '.hpp', '.hxx', '.cuh']) {
            if (!c.endsWith(he) && fileSet.has(c + he)) resolved.push(c + he);
          }
        }
      }
    } else if (ext === '.rb') {
      // Ruby imports
      const content = readFileIfExists(path.join(projectRoot, fp));
      if (!content) { importMap[fp] = []; continue; }
      const relRe = /require_relative\s+['"]([^'"]+)['"]/g;
      while ((match = relRe.exec(content)) !== null) {
        const relPath = match[1];
        const candidate = path.join(dir, relPath + '.rb').replace(/\\/g, '/');
        if (fileSet.has(candidate)) resolved.push(candidate);
      }
      const requireRe = /require\s+['"]([^'"]+)['"]/g;
      while ((match = requireRe.exec(content)) !== null) {
        const reqPath = match[1];
        const candidates = [
          'lib/' + reqPath + '.rb',
          'app/' + reqPath + '.rb',
          reqPath + '.rb',
        ];
        for (const c of candidates) {
          if (fileSet.has(c)) { resolved.push(c); break; }
        }
      }
    }

    importMap[fp] = [...new Set(resolved)].sort();
  }

  return importMap;
}

function readModulePath(goModPath) {
  const content = readFileIfExists(goModPath);
  if (!content) return '';
  const match = content.match(/^module\s+(.+)/m);
  return match ? match[1] : '';
}

// ─── Main ──────────────────────────────────────────────────────────

function main() {
  const projectRoot = process.argv[2];
  const outputPath = process.argv[3];

  if (!projectRoot || !outputPath) {
    logErr('Usage: node ua-project-scan.js <project-root> <output-json-path>');
    process.exit(1);
  }

  const absRoot = path.resolve(projectRoot);
  if (!fs.statSync(absRoot).isDirectory()) {
    logErr(`Error: ${absRoot} is not a directory`);
    process.exit(1);
  }

  // Step 1: Discover files
  let allFiles = discoverFiles(absRoot);
  // Remove .understand-anything/ directory files from consideration
  allFiles = allFiles.filter(f => !f.startsWith('.understand-anything/'));

  // Step 2: Filter
  const { files: filteredFiles, filteredByIgnore } = filterFiles(allFiles, absRoot);

  // Step 3-4: Detect language and category per file
  const fileObjects = filteredFiles.map(fp => ({
    filePath: fp,
    language: detectLanguage(fp),
    fileCategory: detectCategory(fp),
  }));

  // Step 5: Count lines
  const lineCounts = countLines(absRoot, fileObjects.map(f => f.filePath));

  // Step 6: Frameworks
  const frameworks = detectFrameworks(absRoot, filteredFiles, filteredFiles);

  // Step 7: Complexity
  const complexity = estimateComplexity(fileObjects.length);

  // Step 8: Project name
  const name = detectProjectName(absRoot, filteredFiles);

  // Step 9: Import resolution
  const importMap = resolveImports(absRoot, fileObjects);

  // Collect languages
  const languages = [...new Set(fileObjects.map(f => f.language))].sort();

  // Build files array
  const files = fileObjects.map(f => ({
    path: f.filePath,
    language: f.language,
    sizeLines: lineCounts[f.filePath] || 0,
    fileCategory: f.fileCategory,
  })).sort((a, b) => a.path.localeCompare(b.path));

  // Description from package.json or app.py
  let rawDescription = '';
  const pkgJson = parseJSONSafe(path.join(absRoot, 'package.json'));
  if (pkgJson && pkgJson.description) rawDescription = pkgJson.description;

  // Read first 10 lines of README
  let readmeHead = '';
  const readmeFile = filteredFiles.find(f => /^readme\.(md|rst|txt)$/i.test(path.basename(f)));
  if (readmeFile) {
    const content = readFileIfExists(path.join(absRoot, readmeFile));
    if (content) {
      readmeHead = content.split('\n').slice(0, 10).join('\n');
    }
  }

  const output = {
    scriptCompleted: true,
    name: name,
    rawDescription: rawDescription,
    readmeHead: readmeHead,
    languages: languages,
    frameworks: frameworks,
    files: files,
    totalFiles: files.length,
    filteredByIgnore: filteredByIgnore,
    estimatedComplexity: complexity,
    importMap: importMap,
  };

  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, JSON.stringify(output, null, 2), 'utf-8');

  logErr(`[done] Wrote ${files.length} files to ${outputPath}`);
  logErr(`  Languages: ${languages.join(', ')}`);
  logErr(`  Frameworks: ${frameworks.length > 0 ? frameworks.join(', ') : '(none)'}`);
  logErr(`  Complexity: ${complexity}`);

  process.exit(0);
}

main();
