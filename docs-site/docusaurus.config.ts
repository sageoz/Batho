import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

const config: Config = {
  title: 'BATHO',
  tagline: 'Give your AI coding agent a map of your codebase. Reduce token spend, eliminate hallucinations, and ship faster with graph-powered code intelligence.',
  favicon: 'img/batho-logo.svg',

  future: {
    v4: true,
  },

  url: 'https://batho.sageoz.org',
  baseUrl: '/',
  trailingSlash: true,

  organizationName: 'sageoz',
  projectName: 'batho',
  deploymentBranch: 'gh-pages',

  onBrokenLinks: 'throw',

  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  presets: [
    [
      'classic',
      {
        docs: {
          sidebarPath: './sidebars.ts',
          editUrl:
            'https://github.com/sageoz/batho/tree/main/docs-site/',
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],

  themes: [
    '@docusaurus/theme-mermaid',
  ],

  markdown: {
    mermaid: true,
  },

  themeConfig: {
    image: 'img/batho-logo.svg',
    colorMode: {
      defaultMode: 'dark',
      respectPrefersColorScheme: true,
    },
    announcementBar: {
      id: 'v1-release',
      content: 'Batho v1.3.2 is now available! 🎉 Check out the <a href="/docs/whitepaper">Whitepaper</a> for complete documentation.',
      backgroundColor: '#2563EB',
      textColor: '#ffffff',
      isCloseable: true,
    },
    navbar: {
      title: 'BATHO',
      logo: {
        alt: 'Batho Logo',
        src: 'img/batho-logo.svg',
      },
      items: [
        {
          type: 'docSidebar',
          sidebarId: 'docsSidebar',
          position: 'left',
          label: 'Docs',
        },
        {
          type: 'docSidebar',
          sidebarId: 'mcpSidebar',
          position: 'left',
          label: 'MCP',
        },
        {
          type: 'docSidebar',
          sidebarId: 'whitepaperSidebar',
          position: 'left',
          label: 'Whitepaper',
        },
        {
          href: 'https://github.com/sageoz/batho',
          label: 'GitHub',
          position: 'right',
        },
        {
          href: 'https://pypi.org/project/batho/',
          label: 'PyPI',
          position: 'right',
        },
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: 'Get Started',
          items: [
            {
              label: 'Quick Start',
              to: '/docs/getting-started/quick-start',
            },
            {
              label: 'Setup with AI Agent',
              to: '/docs/getting-started/skill-setup',
            },
            {
              label: 'MCP Server',
              to: '/docs/mcp',
            },
          ],
        },
        {
          title: 'Reference',
          items: [
            {
              label: 'Whitepaper',
              to: '/docs/whitepaper',
            },
            {
              label: 'CLI Reference',
              to: '/docs/cli-reference',
            },
            {
              label: 'CI/CD',
              to: '/docs/cicd',
            },
          ],
        },
        {
          title: 'Community',
          items: [
            {
              label: 'GitHub',
              href: 'https://github.com/sageoz/batho',
            },
            {
              label: 'PyPI',
              href: 'https://pypi.org/project/batho/',
            },
          ],
        },
      ],
      copyright: `Copyright © ${new Date().getFullYear()} Sageoz. Built with Docusaurus.`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
