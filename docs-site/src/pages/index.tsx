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
    comment: '# Index your project',
    cmd: 'batho index --root . --snapshot',
    output: 'Indexing repository...\n✓ Parsed 847 files across 12 languages\n✓ Built hypergraph with 1,247 entities, 892 relations\n✓ Snapshot saved to .batho/snapshots/',
  },
  {
    comment: '# Auto-detect and patch changes',
    cmd: 'batho patch --root . --scan',
    output: 'Scanning for changes...\n✓ Detected 3 modified files\n✓ Generated 2 patches (add, update)\n✓ Applied patches successfully',
  },
  {
    comment: '# Generate compressed BSG for LLM injection',
    cmd: 'batho bsg --root . --mode compressed --budget 12000',
    output: 'Generating BSG...\n✓ Selected 42 entities (priority-ranked)\n✓ Compressed to 11,847 tokens (budget: 12000)\n✓ BSG written to stdout',
  },
  {
    comment: '# Launch dashboard',
    cmd: 'batho dashboard',
    output: 'Starting BATHO Dashboard...\n✓ Dashboard server running on http://localhost:8080\n✓ Open browser to explore code graph',
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
            <p className={styles.quickStartDesc}>One command to index your entire codebase.</p>
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
      <div className={styles.heroDecorLeft} aria-hidden="true">{'{ }'}</div>
      <div className={styles.heroDecorRight} aria-hidden="true">{'// idx → graph → bsg'}</div>
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

export default function Home(): ReactNode {
  return (
    <Layout
      title="BATHO — Code Intelligence Engine"
      description="BATHO indexes your codebase, compresses it for LLM context windows, and tracks changes over time. 40+ languages, interactive dashboard, and time-aware hypergraphs.">
      <HomepageHeader />
      <main>
        <HomepageFeatures />
        <QuickStart />
      </main>
    </Layout>
  );
}
