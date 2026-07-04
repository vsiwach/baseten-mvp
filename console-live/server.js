#!/usr/bin/env node
// server.js — local runner: static files + the /api/baseten proxy, no deps.
// Emulates Vercel's req.query (repeated params become arrays).
'use strict';

const http = require('http');
const fs = require('fs');
const path = require('path');
const proxy = require('./api/baseten');

const PORT = Number(process.env.PORT) || 4173;
const ROOT = __dirname;
const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json',
};

http.createServer((req, res) => {
  const url = new URL(req.url, 'http://localhost');
  if (url.pathname === '/api/baseten' || url.pathname.startsWith('/api/baseten/')) {
    req.query = {};
    for (const name of new Set(url.searchParams.keys())) {
      const all = url.searchParams.getAll(name);
      req.query[name] = all.length > 1 ? all : all[0];
    }
    return proxy(req, res);
  }
  const file = path.join(ROOT, url.pathname === '/' ? 'index.html' : url.pathname);
  if (!file.startsWith(ROOT + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
    res.writeHead(404, { 'Content-Type': 'text/plain' });
    return res.end('not found');
  }
  res.writeHead(200, { 'Content-Type': TYPES[path.extname(file)] || 'application/octet-stream' });
  fs.createReadStream(file).pipe(res);
}).listen(PORT, () => console.log(`console-live on http://localhost:${PORT}`));
