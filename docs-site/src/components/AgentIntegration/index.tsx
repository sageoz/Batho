import type {ReactNode} from 'react';
import {useState, useRef, useEffect} from 'react';
import clsx from 'clsx';
import Link from '@docusaurus/Link';
import styles from './styles.module.css';

/* ------------------------------------------------------------------
   Agent data
   ------------------------------------------------------------------ */

interface AgentConfig {
  name: string;
  monogram: string;
  tagline: string;
  configLabel: string;
  configCode: string;
  benefits: string[];
  setupLink: string;
}

const AGENTS: AgentConfig[] = [
  {
    name: 'Claude Code',
    monogram: 'CC',
    tagline: "Anthropic's terminal-first coding agent with the deepest MCP integration.",
    configLabel: 'Terminal',
    configCode: 'claude mcp add batho -- batho mcp',
    benefits: [
      '1M context window + Batho graph = near-zero hallucination on structural queries',
      'Hook system can trigger batho patch automatically after edits',
      '10 MCP tools available as mcp__batho__* in every session',
    ],
    setupLink: '/docs/mcp/setup#claude-desktop',
  },
  {
    name: 'Cursor',
    monogram: 'Cu',
    tagline: "The AI-first IDE with built-in MCP support and Composer agent mode.",
    configLabel: '.cursor/mcp.json',
    configCode: '{\n  "mcpServers": {\n    "batho": {\n      "command": "batho",\n      "args": ["mcp"]\n    }\n  }\n}',
    benefits: [
      'Agent Mode queries the graph instead of grep-ing files',
      '94% fewer tool calls vs. raw file scanning',
      'Auto-configured via SKILL.md — zero manual JSON editing',
    ],
    setupLink: '/docs/mcp/setup#cursor',
  },
  {
    name: 'Windsurf',
    monogram: 'Ws',
    tagline: "Cascade-powered IDE with broad MCP marketplace support.",
    configLabel: '~/.codeium/windsurf/mcp_config.json',
    configCode: '{\n  "mcpServers": {\n    "batho": {\n      "command": "batho",\n      "args": ["mcp"]\n    }\n  }\n}',
    benefits: [
      'Cascade agents use graph queries for refactoring and code review',
      'One-click MCP marketplace install',
      'Multi-repo registry serves all your projects from one server',
    ],
    setupLink: '/docs/mcp/setup#windsurf',
  },
  {
    name: 'Antigravity',
    monogram: 'Ag',
    tagline: "Google's agent-first platform with native MCP over streamable HTTP.",
    configLabel: '~/.gemini/config/mcp_config.json',
    configCode: '{\n  "mcpServers": {\n    "batho": {\n      "command": "batho",\n      "args": ["mcp"]\n    }\n  }\n}',
    benefits: [
      'Gemini 3.5 Flash + Batho graph = fast, accurate structural queries',
      'Unified config across Antigravity IDE, CLI, and SDK',
      'Skills + MCP = agent knows your codebase before writing a line',
    ],
    setupLink: '/docs/mcp/setup#antigravity',
  },
  {
    name: 'Gemini CLI',
    monogram: 'Ge',
    tagline: "Google's open-source terminal agent with 1,000 free requests/day.",
    configLabel: '~/.gemini/config/mcp_config.json',
    configCode: '{\n  "mcpServers": {\n    "batho": {\n      "command": "batho",\n      "args": ["mcp"]\n    }\n  }\n}',
    benefits: [
      'Free tier covers daily Batho-powered coding sessions',
      'GEMINI.md context files + graph queries = grounded answers',
      'Works with the same MCP config as Antigravity',
    ],
    setupLink: '/docs/mcp/setup#gemini-cli',
  },
  {
    name: 'Cline',
    monogram: 'Cl',
    tagline: "Apache-2.0 agent for VS Code, JetBrains, Cursor, and Windsurf.",
    configLabel: 'cline_mcp_settings.json',
    configCode: '{\n  "mcpServers": {\n    "batho": {\n      "command": "batho",\n      "args": ["mcp"],\n      "autoApprove": []\n    }\n  }\n}',
    benefits: [
      'BYOK model — use Batho with any LLM provider',
      'Auto-approve Batho tools for frictionless graph queries',
      'Works across VS Code, JetBrains, and CLI',
    ],
    setupLink: '/docs/mcp/setup#vs-code',
  },
  {
    name: 'OpenCode',
    monogram: 'Oc',
    tagline: "Open-source TUI + desktop app with MCP extensibility.",
    configLabel: '.opencode/config.json',
    configCode: '{\n  "mcpServers": {\n    "batho": {\n      "command": "batho",\n      "args": ["mcp"]\n    }\n  }\n}',
    benefits: [
      'Terminal-native workflow with graph-powered context',
      'BYOK — pair Batho with Claude, GPT, or local models',
      'Diff-first approach + Batho delta = precise change tracking',
    ],
    setupLink: '/docs/mcp/setup',
  },
  {
    name: 'Aider',
    monogram: 'Ai',
    tagline: "The gold standard for terminal pair-programming. Git-native.",
    configLabel: 'Terminal',
    configCode: 'aider --mcp batho',
    benefits: [
      'Git-native workflow + Batho incremental patching = clean history',
      'Repo-map enhanced with structural graph queries',
      'Works with GPT, Claude, Gemini, and local Ollama models',
    ],
    setupLink: '/docs/mcp/setup',
  },
];

/* ------------------------------------------------------------------
   Agent monogram badge
   ------------------------------------------------------------------ */

function AgentMonogram({ monogram, active }: { monogram: string; active: boolean }) {
  return (
    <span
      className={clsx(styles.monogram, active && styles.monogramActive)}
      aria-hidden="true"
    >
      {monogram}
    </span>
  );
}

/* ------------------------------------------------------------------
   Config code block with copy button
   ------------------------------------------------------------------ */

function ConfigBlock({ label, code }: { label: string; code: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className={styles.configBlock}>
      <div className={styles.configHeader}>
        <span className={styles.configLabel}>{label}</span>
        <button
          className={styles.configCopy}
          onClick={handleCopy}
          type="button"
          aria-label="Copy configuration"
        >
          {copied ? 'Copied!' : 'Copy'}
        </button>
      </div>
      <pre className={styles.configPre}>
        <code className={styles.configCode}>{code}</code>
      </pre>
    </div>
  );
}

/* ------------------------------------------------------------------
   Main AgentIntegration component
   ------------------------------------------------------------------ */

export default function AgentIntegration(): ReactNode {
  const [activeTab, setActiveTab] = useState(0);
  const tabListRef = useRef<HTMLDivElement>(null);
  const agent = AGENTS[activeTab];

  // Scroll active tab into view on mobile
  useEffect(() => {
    const tabButton = tabListRef.current?.children[activeTab] as HTMLElement;
    if (tabButton) {
      tabButton.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
    }
  }, [activeTab]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowRight') {
      e.preventDefault();
      setActiveTab((prev) => (prev + 1) % AGENTS.length);
    } else if (e.key === 'ArrowLeft') {
      e.preventDefault();
      setActiveTab((prev) => (prev - 1 + AGENTS.length) % AGENTS.length);
    }
  };

  return (
    <section className={styles.agentIntegration}>
      <div className="container">
        <div className={styles.sectionHeader}>
          <h2 className={styles.sectionTitle}>Works With Your AI Agent</h2>
          <p className={styles.sectionSubtitle}>
            Batho connects to any MCP-compatible coding agent. One config, zero hassle.
            Your agent gets a code graph instead of a file dump.
          </p>
        </div>

        {/* Tab bar */}
        <div
          ref={tabListRef}
          className={styles.tabBar}
          role="tablist"
          aria-label="AI coding agents"
          onKeyDown={handleKeyDown}
        >
          {AGENTS.map((ag, idx) => (
            <button
              key={ag.name}
              className={clsx(
                styles.tabButton,
                idx === activeTab && styles.tabButtonActive
              )}
              role="tab"
              aria-selected={idx === activeTab}
              aria-controls={`agent-panel-${idx}`}
              id={`agent-tab-${idx}`}
              tabIndex={idx === activeTab ? 0 : -1}
              onClick={() => setActiveTab(idx)}
              type="button"
            >
              <AgentMonogram monogram={ag.monogram} active={idx === activeTab} />
              <span className={styles.tabLabel}>{ag.name}</span>
            </button>
          ))}
        </div>

        {/* Tab content */}
        <div
          id={`agent-panel-${activeTab}`}
          role="tabpanel"
          aria-labelledby={`agent-tab-${activeTab}`}
          className={styles.tabPanel}
        >
          <div className={styles.panelGrid}>
            {/* Left: description + benefits */}
            <div className={styles.panelInfo}>
              <h3 className={styles.agentName}>{agent.name}</h3>
              <p className={styles.agentTagline}>{agent.tagline}</p>
              <ul className={styles.benefitList}>
                {agent.benefits.map((benefit, i) => (
                  <li key={i} className={styles.benefitItem}>
                    <span className={styles.benefitCheck} aria-hidden="true">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                        <polyline points="20 6 9 17 4 12" />
                      </svg>
                    </span>
                    <span className={styles.benefitText}>{benefit}</span>
                  </li>
                ))}
              </ul>
              <Link
                className={styles.setupLink}
                to={agent.setupLink}
              >
                Setup Batho with {agent.name}
                <span className={styles.setupLinkArrow} aria-hidden="true">&rarr;</span>
              </Link>
            </div>

            {/* Right: config code block */}
            <div className={styles.panelConfig}>
              <ConfigBlock label={agent.configLabel} code={agent.configCode} />
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
