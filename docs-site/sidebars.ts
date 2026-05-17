import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

// This runs in Node.js - Don't use client-side code here (browser APIs, JSX...)

/**
 * Creating a sidebar enables you to:
 - create an ordered group of docs
 - render a sidebar for each doc of that group
 - provide next/previous navigation

 The sidebars can be generated from the filesystem, or explicitly defined here.

 Create as many sidebars as you want.
 */
const sidebars: SidebarsConfig = {
  docsSidebar: [
    'intro',
    {
      type: 'category',
      label: 'Getting Started',
      items: [
        'getting-started/quick-start',
        'getting-started/installation',
        'getting-started/configuration',
      ],
    },
    {
      type: 'category',
      label: 'API Reference',
      items: [
        'api/rest-api',
        'api/mcp-server',
        'api/bridge-artifacts',
      ],
    },
    {
      type: 'category',
      label: 'Contributing',
      items: [
        'contributing/setup',
        'contributing/guidelines',
        'contributing/architecture',
      ],
    },
    'faq',
    'changelog',
  ],

  whitepaperSidebar: [
    {
      type: 'category',
      label: 'Whitepaper',
      link: {
        type: 'doc',
        id: 'whitepaper/index',
      },
      items: [
        'whitepaper/architecture',
        'whitepaper/core-subsystems',
        'whitepaper/code-graph',
        'whitepaper/bsg-compression',
        'whitepaper/time-machine',
        'whitepaper/git-hooks',
        'whitepaper/dashboard',
        'whitepaper/bridge-mcp',
        'whitepaper/security',
        'whitepaper/performance',
        'whitepaper/deployment',
        'whitepaper/appendix',
      ],
    },
  ],

  cliSidebar: [
    {
      type: 'category',
      label: 'CLI Reference',
      link: {
        type: 'doc',
        id: 'cli-reference/index',
      },
      items: [
        'cli-reference/index-cmd',
        'cli-reference/snapshot-cmd',
        'cli-reference/patch-cmd',
        'cli-reference/bsg-cmd',
        'cli-reference/hooks-cmd',
        'cli-reference/bridge-cmd',
        'cli-reference/dashboard-cmd',
        'cli-reference/storage-cmd',
        'cli-reference/query-cmd',
      ],
    },
  ],
};

export default sidebars;
