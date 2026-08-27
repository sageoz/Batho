# Batho Documentation Site

The official documentation site for [Batho](https://github.com/sageoz/batho) — graph-powered code intelligence for AI coding agents.

Built with [Docusaurus](https://docusaurus.io/).

## Development

```bash
npm install
npm start
```

This starts a local development server at `http://localhost:3000`. Most changes are reflected live without restarting.

## Build

```bash
npm run build
```

Generates static content into the `build/` directory, ready to be served by any static host.

## Deploy

Deploy to GitHub Pages:

```bash
GIT_USER=<your-github-username> npm run deploy
```

This builds the site and pushes to the `gh-pages` branch.

## Structure

```
docs-site/
├── docs/              # Documentation markdown files
├── src/
│   ├── components/    # React components (HomepageFeatures, AgentIntegration)
│   ├── css/           # Custom CSS (Batho design system)
│   └── pages/         # Standalone pages (homepage)
├── static/img/        # Logos, favicons, social cards
├── docusaurus.config.ts
└── sidebars.ts
```

## License

Copyright (c) Sageoz. All rights reserved.
