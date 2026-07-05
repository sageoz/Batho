import type {ReactNode} from 'react';
import {useState, useEffect, useRef} from 'react';
import clsx from 'clsx';
import Link from '@docusaurus/Link';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import Layout from '@theme/Layout';
import HomepageFeatures from '../components/HomepageFeatures';
import AgentIntegration from '../components/AgentIntegration';
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
  {
    comment: '# Start MCP server for your AI agent',
    cmd: 'batho mcp',
    output: 'MCP server running on stdio\n✓ 10 tools available: graph_overview, graph_query, get_entity, ...\n✓ Connect from Claude Code, Cursor, Windsurf, and more',
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
  const [copiedSkill, setCopiedSkill] = useState(false);
  const [copiedCli, setCopiedCli] = useState(false);
  const skillCmd = 'curl -O https://raw.githubusercontent.com/sageoz/batho/main/SKILL.md';
  const cliCmd = 'pip install batho && batho build --root . && batho mcp';

  const handleCopySkill = () => {
    navigator.clipboard.writeText(skillCmd);
    setCopiedSkill(true);
    setTimeout(() => setCopiedSkill(false), 2000);
  };

  const handleCopyCli = () => {
    navigator.clipboard.writeText(cliCmd);
    setCopiedCli(true);
    setTimeout(() => setCopiedCli(false), 2000);
  };

  return (
    <section className={styles.quickStart}>
      <div className="container">
        <div className={styles.quickStartInner}>
          <Animated delay={1}>
            <span className={clsx(styles.sectionEyebrow, styles.sectionEyebrowCentered)}>Quick Start</span>
          </Animated>
          <Animated delay={1}>
            <h2 className={styles.quickStartTitle}>Get Started in Seconds</h2>
          </Animated>
          <Animated delay={2}>
            <p className={styles.quickStartDesc}>
              Two paths to graph-powered coding. Pick the one that fits your workflow.
            </p>
          </Animated>
          <Animated delay={3}>
            <div className={styles.quickStartGrid}>
              {/* Primary: Skill method */}
              <div className={clsx(styles.quickStartCard, styles.quickStartCardPrimary)}>
                <div className={styles.quickStartCardBody}>
                  <div className={styles.quickStartCardInfo}>
                    <div className={styles.quickStartCardHeader}>
                      <div className={styles.quickStartIconWrap}>
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M12 2a10 10 0 1 0 10 10" />
                          <path d="M12 2v10l7-7" />
                          <circle cx="12" cy="12" r="3" />
                        </svg>
                      </div>
                      <div className={styles.quickStartCardHeaderText}>
                        <h3 className={styles.quickStartCardTitle}>Setup with your AI Agent</h3>
                        <span className={styles.quickStartCardMeta}>1 command &middot; ~30 seconds</span>
                      </div>
                    </div>
                    <p className={styles.quickStartCardDesc}>
                      Download the skill file and give it to your agent. It installs Batho, builds the graph, and configures MCP for all detected clients.
                    </p>
                    <Link
                      className={styles.quickStartLink}
                      to="/docs/getting-started/skill-setup">
                      Full guide
                      <span className={styles.quickStartLinkArrow} aria-hidden="true">&rarr;</span>
                    </Link>
                  </div>
                  <div className={styles.quickStartCardAction}>
                    <div className={styles.quickStartCodeBlock}>
                      <span className={styles.quickStartPrompt}>$</span>
                      <code className={styles.quickStartCode}>{skillCmd}</code>
                      <button className={styles.quickStartCopy} onClick={handleCopySkill} type="button">
                        {copiedSkill ? 'Copied!' : 'Copy'}
                      </button>
                    </div>
                    <p className={styles.quickStartHint}>
                      Then tell your agent: <code className={styles.quickStartInlineCode}>Read SKILL.md and set up Batho for this repo</code>
                    </p>
                  </div>
                </div>
              </div>

              {/* Secondary: CLI method */}
              <div className={styles.quickStartCard}>
                <div className={styles.quickStartCardBody}>
                  <div className={styles.quickStartCardInfo}>
                    <div className={styles.quickStartCardHeader}>
                      <div className={styles.quickStartIconWrap}>
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <polyline points="4 17 10 11 4 5" />
                          <line x1="12" y1="19" x2="20" y2="19" />
                        </svg>
                      </div>
                      <div className={styles.quickStartCardHeaderText}>
                        <h3 className={styles.quickStartCardTitle}>Manual CLI Setup</h3>
                        <span className={styles.quickStartCardMeta}>3 commands &middot; ~1 minute</span>
                      </div>
                    </div>
                    <p className={styles.quickStartCardDesc}>
                      Prefer the terminal? Three commands — install, build, start MCP server. No agent required.
                    </p>
                    <Link
                      className={styles.quickStartLink}
                      to="/docs/getting-started/quick-start">
                      CLI quick start
                      <span className={styles.quickStartLinkArrow} aria-hidden="true">&rarr;</span>
                    </Link>
                  </div>
                  <div className={styles.quickStartCardAction}>
                    <div className={styles.quickStartCodeBlock}>
                      <span className={styles.quickStartPrompt}>$</span>
                      <code className={styles.quickStartCode}>{cliCmd}</code>
                      <button className={styles.quickStartCopy} onClick={handleCopyCli} type="button">
                        {copiedCli ? 'Copied!' : 'Copy'}
                      </button>
                    </div>
                    <p className={styles.quickStartHint}>
                      No agent needed — run everything from your terminal. <code className={styles.quickStartInlineCode}>batho mcp</code> starts the MCP server.
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </Animated>
        </div>
      </div>
    </section>
  );
}

const SOCIAL_PROOF_AGENTS = [
  'Claude Code',
  'Cursor',
  'Windsurf',
  'Antigravity',
  'Gemini CLI',
  'Cline',
  'OpenCode',
  'Aider',
];

function SocialProofStrip() {
  return (
    <section className={styles.socialProof}>
      <div className="container">
        <p className={styles.socialProofLabel}>Works with your AI coding agent</p>
        <div className={styles.socialProofLogos}>
          {SOCIAL_PROOF_AGENTS.map((name) => (
            <span key={name} className={styles.socialProofLogo}>
              {name}
            </span>
          ))}
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
        <Animated delay={2}>
          <Heading as="h1" className={styles.heroTitle}>
            BATHO
          </Heading>
        </Animated>
        <Animated delay={3}>
          <p className={styles.heroSubtitle}>
            Give your AI coding agent a map of your codebase.
            <br />
            <em>10x fewer tokens. Zero hallucinations. Ship faster.</em>
          </p>
        </Animated>
        <Animated delay={4}>
          <div className={styles.buttons}>
            <Link
              className="button button--primary button--lg"
              to="/docs/intro">
              Get Started
            </Link>
            <Link
              className="button button--secondary button--lg"
              to="/docs/mcp/setup">
              Setup with Your Agent
            </Link>
          </div>
        </Animated>
        <Animated delay={5}>
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
  meta,
  icon,
  delay,
}: {
  number: string;
  title: string;
  description: string;
  code: string;
  meta: string;
  icon: ReactNode;
  delay: number;
}) {
  const delayClass = `batho-delay-${Math.min(delay, 6)}`;
  return (
    <div className={clsx('batho-animate-fadeInUp', delayClass, styles.workflowStep)}>
      <div className={styles.workflowStepHeader}>
        <div className={styles.workflowIconWrap}>{icon}</div>
        <span className={styles.workflowNumber}>{number}</span>
      </div>
      <h3 className={styles.workflowTitle}>{title}</h3>
      <p className={styles.workflowDesc}>{description}</p>
      <div className={styles.workflowCode}>
        <code>{code}</code>
      </div>
      <span className={styles.workflowMeta}>{meta}</span>
    </div>
  );
}

function UseCases() {
  const cases = [
    {
      title: 'Bug Tracking',
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M8 2v4M16 2v4M8 18l-4 4M16 18l4 4M12 6v12" />
          <rect x="6" y="6" width="12" height="12" rx="6" />
          <path d="M2 12h4M18 12h4" />
        </svg>
      ),
      description: 'Trace root causes across files. Your agent follows the graph — not grep — to find where bugs originate.',
    },
    {
      title: 'Security Audits',
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
          <path d="M9 12l2 2 4-4" />
        </svg>
      ),
      description: 'Map attack surfaces, trace data flows, and identify vulnerable patterns — structurally, not heuristically.',
    },
    {
      title: 'Refactoring',
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M3 6h18M3 12h18M3 18h18" />
          <path d="M7 3v18M17 3v18" opacity="0.4" />
        </svg>
      ),
      description: 'See every dependency before you rename. Your agent knows the blast radius of every change.',
    },
    {
      title: 'Code Review',
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 2a7 7 0 1 0 7 7" />
          <path d="M12 9v4l2 2" />
          <path d="M21 16v5h-5" />
        </svg>
      ),
      description: 'Review PRs with full context. Your agent understands what changed, what depends on it, and why it matters.',
    },
    {
      title: 'Onboarding',
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
          <circle cx="9" cy="7" r="4" />
          <path d="M19 8v6M22 11h-6" />
        </svg>
      ),
      description: 'New team members ask your agent questions. It answers with structural facts — not file dumps.',
    },
    {
      title: 'CI/CD Integration',
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M6 3v12M18 9l-6-6-6 6M18 21v-12M6 15l6 6 6-6" />
        </svg>
      ),
      description: 'Build the graph in CI, export an artifact, and ship it with your deploy. Agents query locally — no server needed.',
    },
  ];

  return (
    <section className={styles.useCases}>
      <div className="container">
        <Animated delay={1}>
          <span className={clsx(styles.sectionEyebrow, styles.sectionEyebrowCentered)}>Capabilities</span>
        </Animated>
        <Animated delay={1}>
          <h2 className={styles.useCasesTitle}>What Your Agent Can Do</h2>
        </Animated>
        <Animated delay={2}>
          <p className={styles.useCasesSubtitle}>
            When cost and quality are solved, automation widens with imagination. Here's what becomes possible.
          </p>
        </Animated>
        <div className={styles.useCasesGrid}>
          {cases.map((c, idx) => (
            <div
              key={c.title}
              className={clsx(
                'batho-animate-fadeInUp',
                `batho-delay-${Math.min(idx + 1, 6)}`,
                styles.useCaseCard
              )}>
              <div className={styles.useCaseIconWrap}>{c.icon}</div>
              <h3 className={styles.useCaseTitle}>{c.title}</h3>
              <p className={styles.useCaseDesc}>{c.description}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function Workflow() {
  const steps = [
    {
      number: '01',
      title: 'Build',
      description: 'Parse your entire codebase into a structured hypergraph with cross-file symbol resolution.',
      code: 'batho build --root .',
      meta: '~3s for 300 files',
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
          <polyline points="3.27 6.96 12 12.01 20.73 6.96" />
          <line x1="12" y1="22.08" x2="12" y2="12" />
        </svg>
      ),
    },
    {
      number: '02',
      title: 'Patch',
      description: 'Apply incremental updates 10-100x faster than full re-indexing using native content hashing.',
      code: 'batho patch --root .',
      meta: '~85ms per PR',
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 20h9M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />
        </svg>
      ),
    },
    {
      number: '03',
      title: 'Export',
      description: 'Export a transportable ZIP artifact by default, or use --json for LLM-optimized views.',
      code: 'batho export --root .',
      meta: '12 MiB typical',
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
          <polyline points="7 10 12 15 17 10" />
          <line x1="12" y1="15" x2="12" y2="3" />
        </svg>
      ),
    },
    {
      number: '04',
      title: 'Verify',
      description: 'Execute integrity checks and diagnostic routines to repair database corruption or inconsistencies.',
      code: 'batho fix --dry-run',
      meta: 'Cryptographic',
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M9 12l2 2 4-4" />
          <path d="M21 12c0 4.97-4.03 9-9 9s-9-4.03-9-9 4.03-9 9-9 9 4.03 9 9z" />
        </svg>
      ),
    },
  ];

  return (
    <section className={styles.workflow}>
      <div className="container">
        <Animated delay={1}>
          <span className={clsx(styles.sectionEyebrow, styles.sectionEyebrowCentered)}>Workflow</span>
        </Animated>
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
  const metrics = [
    { value: '10x', label: 'Less Tokens', desc: 'vs. raw file injection' },
    { value: '0', label: 'Hallucinations', desc: 'deterministic, not guessed' },
    { value: '40+', label: 'Languages', desc: 'tree-sitter powered' },
    { value: '8', label: 'AI Agents', desc: 'MCP-compatible out of the box' },
    { value: '>95%', label: 'Cache Hit', desc: 'typical PR changes' },
  ];
  const benefits = [
    {
      title: 'Slash Token Costs',
      color: '#EEAE31',
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
        </svg>
      ),
      description: 'Your agent queries a graph instead of reading entire files. 10x fewer tokens per task — no more dumping your repo into the LLM.',
    },
    {
      title: 'Eliminate Hallucinations',
      color: '#16AD7B',
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M9 12l2 2 4-4M21 12c0 4.97-4.03 9-9 9s-9-4.03-9-9 4.03-9 9-9 9 4.03 9 9z" />
        </svg>
      ),
      description: 'Deterministic, tree-sitter-parsed relationships. Your agent gets facts, not guesses — zero hallucinations on structural queries.',
    },
    {
      title: 'Agent Superpowers',
      color: '#9060F3',
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M6 3v12M18 9l-6-6-6 6M18 21v-12M6 15l6 6 6-6" />
        </svg>
      ),
      description: 'Bug tracking, security audits, refactoring, code review — your agent handles more, accurately. When cost and quality are solved, automation widens with imagination.',
    },
  ];

  return (
    <section className={styles.benefits}>
      <div className="container">
        <Animated delay={1}>
          <span className={clsx(styles.sectionEyebrow, styles.sectionEyebrowCentered)}>Why Batho</span>
        </Animated>
        <Animated delay={1}>
          <h2 className={styles.benefitsTitle}>The Problem Batho Solves</h2>
        </Animated>
        <Animated delay={2}>
          <p className={styles.benefitsSubtitle}>
            AI coding agents are powerful — but they burn tokens reading files and hallucinate when context is thin.
            Batho gives your agent a structured code graph so it works smarter, not harder.
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
              )}
              style={{'--benefit-accent': b.color, '--benefit-accent-soft': `${b.color}1A`} as React.CSSProperties}>
              <div className={styles.benefitCardAccent} aria-hidden="true" />
              <div className={styles.benefitCardInner}>
                <div className={styles.benefitIconWrap}>{b.icon}</div>
                <h3 className={styles.benefitCardTitle}>{b.title}</h3>
                <p className={styles.benefitCardDesc}>{b.description}</p>
              </div>
            </div>
          ))}
        </div>
        <div className={styles.metricsDivider} role="separator" aria-hidden="true" />
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
      <div className={styles.ctaOrb1} aria-hidden="true" />
      <div className={styles.ctaOrb2} aria-hidden="true" />
      <div className="container">
        <div className={styles.ctaInner}>
          <Animated delay={1}>
            <div className={styles.ctaEyebrow}>
              <svg viewBox="0 0 24 24" fill="currentColor" width="14" height="14">
                <path d="M12 .587l3.668 7.568 8.332 1.151-6.064 5.828 1.48 8.279L12 19.446l-7.416 3.967 1.48-8.279L0 9.306l8.332-1.151z" />
              </svg>
              <span>Open Source</span>
            </div>
          </Animated>
          <Animated delay={2}>
            <h2 className={styles.ctaTitle}>Give your AI agent a code graph — not a file dump.</h2>
          </Animated>
          <Animated delay={3}>
            <p className={styles.ctaSubtitle}>
              Index in one command. Connect via MCP. Your agent gets structural intelligence
              with zero-copy speed, 10x fewer tokens, and zero hallucinations.
            </p>
          </Animated>
          <Animated delay={4}>
            <ul className={styles.ctaHighlights}>
              <li>One command to build</li>
              <li>Works with 8+ AI agents</li>
              <li>No server required</li>
            </ul>
          </Animated>
          <Animated delay={5}>
            <div className={styles.ctaButtons}>
              <Link
                className={clsx('button button--primary button--lg', styles.ctaButtonPrimary)}
                to="/docs/getting-started/quick-start">
                Get Started
              </Link>
              <Link
                className={clsx('button button--secondary button--lg', styles.ctaButtonSecondary)}
                to="https://github.com/sageoz/batho">
                <svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18" style={{marginRight: 8}}>
                  <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z" />
                </svg>
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
      title="BATHO — Code Graph Intelligence for AI Coding Agents"
      description="Batho gives your AI coding agent a structured code graph instead of raw files. Reduce token spend 10x, eliminate hallucinations, and connect via MCP to Claude Code, Cursor, Windsurf, Antigravity, Gemini CLI, Cline, OpenCode, and Aider.">
      <HomepageHeader />
      <SocialProofStrip />
      <main>
        <BenefitsSection />
        <Workflow />
        <HomepageFeatures />
        <UseCases />
        <AgentIntegration />
        <QuickStart />
        <CTABanner />
      </main>
    </Layout>
  );
}
