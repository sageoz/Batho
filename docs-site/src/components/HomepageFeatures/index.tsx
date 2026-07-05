import type {ReactNode} from 'react';
import clsx from 'clsx';
import Link from '@docusaurus/Link';
import Heading from '@theme/Heading';
import styles from './styles.module.css';

type FeatureItem = {
  title: string;
  icon: ReactNode;
  description: ReactNode;
  link?: string;
};

const FeatureList: FeatureItem[] = [
  {
    title: 'Works With Your Stack',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
        <polyline points="14,2 14,8 20,8" />
        <line x1="16" y1="13" x2="8" y2="13" />
        <line x1="16" y1="17" x2="8" y2="17" />
      </svg>
    ),
    description: (
      <>
        Python, TypeScript, Rust, Go, Java, and more. Batho parses 40+ languages
        so your AI agent understands your entire codebase — no blind spots.
      </>
    ),
    link: '/docs/whitepaper/code-graph',
  },
  {
    title: 'Spend Less on Tokens',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="3" width="18" height="18" rx="2" />
        <line x1="3" y1="9" x2="21" y2="9" />
        <line x1="9" y1="21" x2="9" y2="9" />
      </svg>
    ),
    description: (
      <>
        Batho compresses entire codebases into a graph your agent traverses —
        using a fraction of the tokens.
      </>
    ),
    link: '/docs/whitepaper/bsg-compression',
  },
  {
    title: 'Track Codebase Evolution',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10" />
        <polyline points="12,6 12,12 16,14" />
      </svg>
    ),
    description: (
      <>
        Versioned snapshots and incremental diffing let your agent understand
        what changed and why — across every commit.
      </>
    ),
    link: '/docs/whitepaper/time-machine',
  },
  {
    title: 'Zero-Copy Performance',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <ellipse cx="12" cy="5" rx="9" ry="3" />
        <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
        <path d="M3 12c0 1.66 4 3 9 3s9-1.34 9-3" />
      </svg>
    ),
    description: (
      <>
        Apache Arrow IPC storage means zero-copy, memory-mapped reads. Your
        agent queries the graph instantly.
      </>
    ),
    link: '/docs/whitepaper/time-machine',
  },
  {
    title: 'Reconstruct Anything',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="m7 15 5 5 5-5" />
        <path d="m7 9 5-5 5 5" />
        <path d="M12 4v16" />
      </svg>
    ),
    description: (
      <>
        Reconstruct any file byte-for-byte from the graph. Cryptographic hash
        integrity means nothing is lost.
      </>
    ),
    link: '/docs/whitepaper/code-graph',
  },
  {
    title: 'Zero Config to Start',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="3" />
        <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
      </svg>
    ),
    description: (
      <>
        Batho runs with zero config. Customize with a single YAML file when
        you need control.
      </>
    ),
    link: '/docs/getting-started/configuration',
  },
  {
    title: 'MCP-Native',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 2a10 10 0 1 0 10 10" />
        <path d="M12 2v10l7-7" />
        <circle cx="12" cy="12" r="3" />
      </svg>
    ),
    description: (
      <>
        Works with Claude Code, Cursor, Windsurf, Antigravity, Gemini CLI,
        Cline, OpenCode, and Aider. One MCP config, zero hassle.
      </>
    ),
    link: '/docs/mcp/setup',
  },
];

function Feature({title, icon, description, link, delay}: FeatureItem & {delay: number}) {
  const delayClass = `batho-delay-${Math.min(delay, 6)}`;
  return (
    <div className={clsx('col col--4', styles.featureCol)}>
      <div className={clsx('batho-animate-fadeInUp', delayClass, styles.featureCard)}>
        <div className={styles.featureIconWrap}>{icon}</div>
        <Heading as="h3" className={styles.featureTitle}>
          {title}
        </Heading>
        <p className={styles.featureDesc}>{description}</p>
        {link && (
          <Link className={styles.featureLink} to={link}>
            Learn more <span className={styles.featureLinkArrow}>→</span>
          </Link>
        )}
      </div>
    </div>
  );
}

export default function HomepageFeatures(): ReactNode {
  return (
    <section className={styles.features}>
      <div className="container">
        <div className="row">
          {FeatureList.map((props, idx) => (
            <Feature key={idx} {...props} delay={idx + 1} />
          ))}
        </div>
      </div>
    </section>
  );
}
