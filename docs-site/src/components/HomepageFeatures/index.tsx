import type {ReactNode} from 'react';
import clsx from 'clsx';
import Heading from '@theme/Heading';
import styles from './styles.module.css';

type FeatureItem = {
  title: string;
  icon: ReactNode;
  description: ReactNode;
};

const FeatureList: FeatureItem[] = [
  {
    title: '40+ Language AST Parsing',
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
        Python, TypeScript, Rust, Go, Java, and more — extracted via tree-sitter
        into structured entities and relationships.
      </>
    ),
  },
  {
    title: '10x Context Compression',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="3" width="18" height="18" rx="2" />
        <line x1="3" y1="9" x2="21" y2="9" />
        <line x1="9" y1="21" x2="9" y2="9" />
      </svg>
    ),
    description: (
      <>
        BSG (Batho Structured Graph) compresses entire codebases into
        token-budgeted formats for LLM injection.
      </>
    ),
  },
  {
    title: 'Time Machine Snapshots',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10" />
        <polyline points="12,6 12,12 16,14" />
      </svg>
    ),
    description: (
      <>
        Track codebase evolution with versioned snapshots, incremental diffing,
        and patch chaining.
      </>
    ),
  },
  {
    title: 'Interactive Dashboard',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="2" y="3" width="20" height="14" rx="2" />
        <line x1="8" y1="10" x2="16" y2="10" />
        <line x1="12" y1="17" x2="12" y2="10" />
      </svg>
    ),
    description: (
      <>
        Web-based hypergraph visualization, file explorer, metrics, search, and
        relationship mapping.
      </>
    ),
  },
  {
    title: 'Artifact Bridge',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
        <polyline points="17,8 12,3 7,8" />
        <line x1="12" y1="3" x2="12" y2="15" />
      </svg>
    ),
    description: (
      <>
        REST API + MCP server for IDE integrations and tool orchestration.
      </>
    ),
  },
  {
    title: 'Git Hooks Enterprise',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M10 13a5 5 0 0 1 7-7 4 4 0 1 1 1 1" />
        <path d="M15 13a5 5 0 0 1-7 7 4 4 0 1 1-1-1" />
        <line x1="2" y1="8" x2="22" y2="8" />
        <line x1="4" y1="16" x2="20" y2="16" />
      </svg>
    ),
    description: (
      <>
        YAML-driven client-side hook automation with stage-based execution.
      </>
    ),
  },
];

function Feature({title, icon, description, delay}: FeatureItem & {delay: number}) {
  const delayClass = `batho-delay-${Math.min(delay, 6)}`;
  return (
    <div className={clsx('col col--4', styles.featureCol)}>
      <div className={clsx('batho-animate-fadeInUp', delayClass, styles.featureCard)}>
        <div className={styles.featureIconWrap}>{icon}</div>
        <Heading as="h3" className={styles.featureTitle}>
          {title}
        </Heading>
        <p className={styles.featureDesc}>{description}</p>
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
