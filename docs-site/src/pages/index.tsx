import type {ReactNode} from 'react';
import {useState, useEffect, useRef} from 'react';
import clsx from 'clsx';
import Link from '@docusaurus/Link';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import Layout from '@theme/Layout';
import HomepageFeatures from '../components/HomepageFeatures';
import Heading from '@theme/Heading';

import styles from './index.module.css';

/* ------------------------------------------------------------------
   Animated entrance wrapper
   ------------------------------------------------------------------ */
function Animated({
  children,
  delay = 0,
  className,
}: {
  children: ReactNode;
  delay?: number;
  className?: string;
}) {
  const delayClass = delay > 0 ? `batho-delay-${Math.min(delay, 6)}` : '';
  return (
    <div className={clsx('batho-animate-fadeInUp', delayClass, className)}>
      {children}
    </div>
  );
}

type TokenType = 'comment' | 'command' | 'flag' | 'arg' | 'plain';

interface Token {
  type: TokenType;
  text: string;
}

function tokenizeBash(line: string): Token[] {
  const tokens: Token[] = [];
  const commentIdx = line.indexOf('#');
  if (commentIdx >= 0) {
    if (commentIdx > 0) {
      tokens.push(...tokenizeBash(line.slice(0, commentIdx)));
    }
    tokens.push({ type: 'comment', text: line.slice(commentIdx) });
    return tokens;
  }

  const parts = line.match(/(\s+|\-\-?[\w-]+|[^\s\-]+)/g) || [line];
  let firstWord = true;
  for (const part of parts) {
    if (/^\s+$/.test(part)) {
      tokens.push({ type: 'plain', text: part });
      continue;
    }
    if (firstWord) {
      tokens.push({ type: 'command', text: part });
      firstWord = false;
      continue;
    }
    if (part.startsWith('-')) {
      tokens.push({ type: 'flag', text: part });
      continue;
    }
    tokens.push({ type: 'arg', text: part });
  }
  return tokens;
}

interface CommandLine {
  comment?: string;
  cmd: string;
  output: string;
}

const COMMAND_LINES: CommandLine[] = [
  {
    comment: '# Build full hypergraph (baseline)',
    cmd: 'batho build --root . --verbose',
    output: 'Building repository...\n✓ Discovered 312 files\n✓ Built hypergraph: 1542 entities, 4823 relationships\n✓ Arrow IPC Bundle created in .batho/artifact/',
  },
  {
    comment: '# Auto-detect and patch changes',
    cmd: 'batho patch --root .',
    output: 'Scanning content hashes...\n✓ Detected 3 modified files\n✓ Patched successfully: 3 changes (2 added, 1 modified) in 85ms',
  },
  {
    comment: '# Export transport artifact',
    cmd: 'batho export --root .',
    output: 'Exporting transport artifact...\n✓ Packed 6 IPC tables (zstd-compressed)\n✓ Artifact: artifact_batho-v1-1-0.batho (12.4 MiB)\n✓ Ready for download or CI/CD upload',
  },
  {
    comment: '# Run integrity verification',
    cmd: 'batho fix --dry-run',
    output: 'Running diagnostics...\n✓ Arrow database: verified\n✓ Run history chain: verified\n✓ Graph consistency: verified\n✓ Integrity intact',
  },
];

function TokenSpan({ token }: { token: Token }) {
  const classMap: Record<TokenType, string> = {
    comment: styles.syntaxComment,
    command: styles.syntaxCommand,
    flag: styles.syntaxFlag,
    arg: styles.syntaxArg,
    plain: styles.syntaxPlain,
  };
  return <span className={classMap[token.type]}>{token.text}</span>;
}

function CodePreview() {
  const [currentLine, setCurrentLine] = useState(0);
  const [typedText, setTypedText] = useState('');
  const [isTyping, setIsTyping] = useState(true);
  const [showOutput, setShowOutput] = useState(false);
  const terminalBodyRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (currentLine >= COMMAND_LINES.length) {
      const timeout = setTimeout(() => {
        setCurrentLine(0);
        setTypedText('');
        setIsTyping(true);
        setShowOutput(false);
      }, 5000);
      return () => clearTimeout(timeout);
    }

    const line = COMMAND_LINES[currentLine];
    const fullText = line.cmd;

    if (isTyping) {
      if (typedText.length < fullText.length) {
        const timeout = setTimeout(() => {
          setTypedText(fullText.slice(0, typedText.length + 1));
        }, 50 + Math.random() * 30);
        return () => clearTimeout(timeout);
      } else {
        setIsTyping(false);
        setShowOutput(true);
        return;
      }
    } else {
      const timeout = setTimeout(() => {
        setCurrentLine(prev => prev + 1);
        setTypedText('');
        setIsTyping(true);
        setShowOutput(false);
      }, 3500);
      return () => clearTimeout(timeout);
    }
  }, [typedText, isTyping, currentLine]);

  useEffect(() => {
    if (terminalBodyRef.current) {
      terminalBodyRef.current.scrollTop = terminalBodyRef.current.scrollHeight;
    }
  }, [currentLine, typedText, showOutput]);

  return (
    <div className={styles.terminalWrapper}>
      <div className={styles.terminal}>
        <div className={styles.terminalChrome}>
          <div className={styles.trafficLights}>
            <span className={clsx(styles.trafficLight, styles.lightRed)} />
            <span className={clsx(styles.trafficLight, styles.lightYellow)} />
            <span className={clsx(styles.trafficLight, styles.lightGreen)} />
          </div>
          <span className={styles.terminalTitle}>BATHO — zsh</span>
          <div className={styles.terminalStatus}>
            <span className={clsx(styles.statusDot, isTyping && styles.statusDotActive)} />
            <span className={styles.statusText}>{isTyping ? 'typing…' : 'ready'}</span>
          </div>
        </div>
        <div ref={terminalBodyRef} className={styles.terminalBody}>
          <pre className={styles.terminalPre}>
            <code>
              {COMMAND_LINES.slice(0, currentLine).map((line, i) => (
                <div key={i} className={styles.terminalLineGroup}>
                  {line.comment && (
                    <div className={styles.terminalComment}>{line.comment}</div>
                  )}
                  <div className={styles.terminalInputLine}>
                    <span className={styles.terminalPrompt}>➜</span>
                    <span className={styles.terminalPath}>~</span>
                    <span className={styles.terminalCmd}>
                      {tokenizeBash(line.cmd).map((t, j) => (
                        <TokenSpan key={j} token={t} />
                      ))}
                    </span>
                  </div>
                  <div className={styles.terminalOutput}>{line.output}</div>
                </div>
              ))}
              {currentLine < COMMAND_LINES.length && (
                <div className={styles.terminalLineGroup}>
                  {COMMAND_LINES[currentLine].comment && (
                    <div className={styles.terminalComment}>
                      {COMMAND_LINES[currentLine].comment}
                    </div>
                  )}
                  <div className={styles.terminalInputLine}>
                    <span className={styles.terminalPrompt}>➜</span>
                    <span className={styles.terminalPath}>~</span>
                    <span className={styles.terminalCmd}>
                      {tokenizeBash(typedText).map((t, j) => (
                        <TokenSpan key={j} token={t} />
                      ))}
                    </span>
                    <span className={styles.terminalCursor}>▋</span>
                  </div>
                  {showOutput && (
                    <div className={styles.terminalOutput}>
                      {COMMAND_LINES[currentLine].output}
                    </div>
                  )}
                </div>
              )}
            </code>
          </pre>
        </div>
      </div>
    </div>
  );
}

function QuickStart() {
  const [copied, setCopied] = useState(false);
  const cmd = 'pip install batho';
  const handleCopy = () => {
    navigator.clipboard.writeText(cmd);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <section className={styles.quickStart}>
      <div className="container">
        <div className={styles.quickStartInner}>
          <Animated delay={1}>
            <h2 className={styles.quickStartTitle}>Get Started in Seconds</h2>
          </Animated>
          <Animated delay={2}>
            <p className={styles.quickStartDesc}>One command to give your AI agent a map of your entire codebase.</p>
          </Animated>
          <Animated delay={3}>
            <div className={styles.quickStartCodeBlock}>
              <span className={styles.quickStartPrompt}>$</span>
              <code className={styles.quickStartCode}>{cmd}</code>
              <button className={styles.quickStartCopy} onClick={handleCopy} type="button">
                {copied ? 'Copied!' : 'Copy'}
              </button>
            </div>
          </Animated>
        </div>
      </div>
    </section>
  );
}

function HomepageHeader() {
  const {siteConfig} = useDocusaurusContext();
  return (
    <header className={clsx('hero', styles.heroBanner)}>
      {/* Subtle grid background */}
      <div className={styles.heroGrid} aria-hidden="true" />
      {/* Animated gradient orbs */}
      <div className={styles.heroOrb1} aria-hidden="true" />
      <div className={styles.heroOrb2} aria-hidden="true" />
      <div className={clsx('container', styles.heroContainer)}>
        <Animated delay={1}>
          <Heading as="h1" className={styles.heroTitle}>
            {siteConfig.title}
          </Heading>
        </Animated>
        <Animated delay={2}>
          <p className={styles.heroSubtitle}>{siteConfig.tagline}</p>
        </Animated>
        <Animated delay={3}>
          <div className={styles.buttons}>
            <Link
              className="button button--primary button--lg"
              to="/docs/intro">
              Get Started
            </Link>
            <Link
              className="button button--secondary button--lg"
              to="/docs/whitepaper">
              Read Whitepaper
            </Link>
          </div>
        </Animated>
        <Animated delay={4}>
          <CodePreview />
        </Animated>
      </div>
    </header>
  );
}

function WorkflowStep({
  number,
  title,
  description,
  code,
  delay,
}: {
  number: string;
  title: string;
  description: string;
  code: string;
  delay: number;
}) {
  const delayClass = `batho-delay-${Math.min(delay, 6)}`;
  return (
    <div className={clsx('batho-animate-fadeInUp', delayClass, styles.workflowStep)}>
      <div className={styles.workflowNumber}>{number}</div>
      <h3 className={styles.workflowTitle}>{title}</h3>
      <p className={styles.workflowDesc}>{description}</p>
      <div className={styles.workflowCode}>
        <code>{code}</code>
      </div>
    </div>
  );
}

function Workflow() {
  const steps = [
    {
      number: '01',
      title: 'Build',
      description: 'Parse your entire codebase into a structured hypergraph with cross-file symbol resolution.',
      code: 'batho build --root .',
    },
    {
      number: '02',
      title: 'Patch',
      description: 'Apply incremental updates 10-100x faster than full re-indexing using native content hashing.',
      code: 'batho patch --root .',
    },
    {
      number: '03',
      title: 'Export',
      description: 'Export a transportable ZIP artifact by default, or use --json for LLM-optimized views.',
      code: 'batho export --root .',
    },
    {
      number: '04',
      title: 'Verify',
      description: 'Execute integrity checks and diagnostic routines to repair database corruption or inconsistencies.',
      code: 'batho fix --dry-run',
    },
  ];

  return (
    <section className={styles.workflow}>
      <div className="container">
        <Animated delay={1}>
          <h2 className={styles.workflowSectionTitle}>How It Works</h2>
        </Animated>
        <Animated delay={2}>
          <p className={styles.workflowSectionSubtitle}>
            From source code to AI-ready graph in four steps
          </p>
        </Animated>
        <div className={styles.workflowGrid}>
          {steps.map((step, idx) => (
            <WorkflowStep key={step.number} {...step} delay={idx + 2} />
          ))}
        </div>
      </div>
    </section>
  );
}

function BenefitsSection() {
  const benefits = [
    {
      title: 'Lower Token Costs',
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
        </svg>
      ),
      description: 'Your agent traverses a graph instead of reading entire files. Feed the LLM only what it needs.',
    },
    {
      title: 'Fewer Hallucinations',
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M9 12l2 2 4-4M21 12c0 4.97-4.03 9-9 9s-9-4.03-9-9 4.03-9 9-9 9 4.03 9 9z" />
        </svg>
      ),
      description: 'Deterministic, tree-sitter-parsed relationships. No guessing, no embeddings — just facts.',
    },
    {
      title: 'More Use Cases',
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M6 3v12M18 9l-6-6-6 6M18 21v-12M6 15l6 6 6-6" />
        </svg>
      ),
      description: 'When cost and accuracy are solved, automation possibilities widen with imagination.',
    },
  ];

  return (
    <section className={styles.benefits}>
      <div className="container">
        <Animated delay={1}>
          <h2 className={styles.benefitsTitle}>Why Batho?</h2>
        </Animated>
        <Animated delay={2}>
          <p className={styles.benefitsSubtitle}>
            Companies are reducing AI usage because token spend is getting pricey. Batho fixes cost and quality.
          </p>
        </Animated>
        <div className={styles.benefitsGrid}>
          {benefits.map((b, idx) => (
            <div
              key={b.title}
              className={clsx(
                'batho-animate-fadeInUp',
                `batho-delay-${Math.min(idx + 2, 6)}`,
                styles.benefitCard
              )}>
              <div className={styles.benefitIconWrap}>{b.icon}</div>
              <h3 className={styles.benefitCardTitle}>{b.title}</h3>
              <p className={styles.benefitCardDesc}>{b.description}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function Metrics() {
  const metrics = [
    { value: '10x', label: 'Less Tokens', desc: 'vs. raw file injection' },
    { value: '0', label: 'Hallucinations', desc: 'deterministic, not guessed' },
    { value: '40+', label: 'Languages', desc: 'tree-sitter powered' },
    { value: '>95%', label: 'Cache Hit', desc: 'typical PR changes' },
  ];

  return (
    <section className={styles.metrics}>
      <div className="container">
        <div className={styles.metricsGrid}>
          {metrics.map((m, idx) => (
            <div
              key={m.label}
              className={clsx(
                'batho-animate-fadeInUp',
                `batho-delay-${Math.min(idx + 1, 6)}`,
                styles.metricCard
              )}>
              <div className={styles.metricValue}>{m.value}</div>
              <div className={styles.metricLabel}>{m.label}</div>
              <div className={styles.metricDesc}>{m.desc}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function CTABanner() {
  return (
    <section className={styles.ctaBanner}>
      <div className="container">
        <div className={styles.ctaInner}>
          <Animated delay={1}>
            <h2 className={styles.ctaTitle}>Stop paying to dump your repo into an LLM.</h2>
          </Animated>
          <Animated delay={2}>
            <p className={styles.ctaSubtitle}>
              Index your codebase in one command. Your AI agent gets the map — not the whole territory.
            </p>
          </Animated>
          <Animated delay={3}>
            <div className={styles.ctaButtons}>
              <Link
                className={clsx('button button--primary button--lg', styles.ctaButtonPrimary)}
                to="/docs/getting-started/quick-start">
                Get Started
              </Link>
              <Link
                className={clsx('button button--secondary button--lg', styles.ctaButtonSecondary)}
                to="https://github.com/sageoz/batho">
                View on GitHub
              </Link>
            </div>
          </Animated>
        </div>
      </div>
    </section>
  );
}

export default function Home(): ReactNode {
  return (
    <Layout
      title="BATHO — Spend Less. Hallucinate Less. Automate More."
      description="Batho reduces token spend and hallucinations by indexing your codebase into a navigable code graph. Power bug tracking, security checks, and any AI workflow without dumping whole repositories into the LLM.">
      <HomepageHeader />
      <main>
        <BenefitsSection />
        <HomepageFeatures />
        <Workflow />
        <Metrics />
        <QuickStart />
        <CTABanner />
      </main>
    </Layout>
  );
}
