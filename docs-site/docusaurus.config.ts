import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

const config: Config = {
  title: 'Batho',
  tagline: 'Bidirectional AST Traversal & Hypergraph Orchestrator',
  favicon: 'img/batho-logo.svg',

  future: {
    v4: true,
  },

  url: 'https://sageoz.github.io',
  baseUrl: '/batho/',
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
    navbar: {
      title: 'Batho',
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
          sidebarId: 'whitepaperSidebar',
          position: 'left',
          label: 'Whitepaper',
        },
        {
          type: 'docSidebar',
          sidebarId: 'cliSidebar',
          position: 'left',
          label: 'CLI',
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
          title: 'Docs',
          items: [
            {
              label: 'Getting Started',
              to: '/docs/getting-started/quick-start',
            },
            {
              label: 'Whitepaper',
              to: '/docs/whitepaper',
            },
            {
              label: 'CLI Reference',
              to: '/docs/cli-reference',
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
        {
          title: 'Legal',
          items: [
            {
              label: 'License',
              href: 'https://github.com/sageoz/batho/blob/main/LICENSE',
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
