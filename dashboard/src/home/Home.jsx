import { useState } from "react";
import { DASHBOARD, PRIVACY, TERMS, routeHref } from "../lib/route.js";
import { SITE_ONLY } from "../lib/site.js";
import { HeroScene } from "./HeroScene.jsx";

export const GITHUB = "https://github.com/Shreya-724/tokenguard";
const PYPI = "https://pypi.org/project/tokenguard-ratelimit/";
const DEMO = `${GITHUB}#dashboard-and-demo`;
const docs = (name) => `${GITHUB}/blob/main/docs/${name}`;

const INSTALL = 'pip install "tokenguard-ratelimit[django]"';

const SNIPPET = `# settings.py
MIDDLEWARE = [
    # ...Django's own middleware, then:
    "tokenguard.django.middleware.TokenGuardMiddleware",
]

# views.py
from tokenguard.django import rate_limit
from tokenguard.django.llm import llm_cost, llm_usage, user_model


@rate_limit(
    capacity=10_000,       # a burst of 10,000 tokens
    refill_rate=50,        # then 50 tokens a second
    key=user_model,        # one bucket per user and model
    cost=llm_cost(),       # charge an estimate up front
    usage=llm_usage(),     # settle to the real usage afterwards
)
def complete(request):
    ...`;

function Mark() {
  return (
    <svg className="mark" viewBox="0 0 32 32" aria-hidden="true">
      <circle cx="16" cy="16" r="14" fill="currentColor" />
      <circle cx="16" cy="16" r="7" fill="none" stroke="var(--navy)" strokeWidth="3" />
      <rect x="22" y="14.5" width="12" height="3" fill="var(--coral)" />
    </svg>
  );
}

/** Copies `text`. `state` is "idle", "copied" or "failed" (clipboard blocked by the browser). */
function useCopy(text) {
  const [state, setState] = useState("idle");
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setState("copied");
    } catch {
      setState("failed");
    }
    setTimeout(() => setState("idle"), 2400);
  };
  return [state, copy];
}

const copyLabel = (state, idle) =>
  state === "copied" ? "Copied" : state === "failed" ? "Copy blocked: select the text" : idle;

// The button to the dashboard. The website build has no dashboard (it needs Django
// and Redis behind it), so there the button says so and goes to the steps to run it.
function DashboardButton({ big = false }) {
  const size = big ? " h-btn-big" : "";
  if (SITE_ONLY) {
    return (
      <a className={`h-btn h-btn-coral${size}`} href={DEMO} rel="noreferrer">
        Run the dashboard locally
      </a>
    );
  }
  return (
    <a className={`h-btn h-btn-coral${size}`} href={routeHref(DASHBOARD)}>
      Open the dashboard
    </a>
  );
}

export function Header({ minimal = false }) {
  return (
    <header className="h-header">
      <div className="h-wrap h-header-row">
        <a className="h-brand" href="#/" aria-label="tokenguard home">
          <Mark />
          tokenguard
        </a>
        {minimal ? null : (
          <nav className="h-nav" aria-label="Page sections">
            <a href="#how">How it works</a>
            <a href="#install">Install</a>
            <a href="#numbers">Numbers</a>
            <a href={GITHUB} rel="noreferrer">
              GitHub
            </a>
          </nav>
        )}
        <DashboardButton />
      </div>
    </header>
  );
}

function Hero() {
  const [copyState, copy] = useCopy(INSTALL);
  return (
    <section className="h-hero">
      <div className="h-wrap h-hero-grid">
        <div className="h-hero-copy">
          <h1>Limit LLM traffic by what each request costs.</h1>
          <p className="h-lead">
            tokenguard is a Redis-backed rate limiter for Django. It charges each request by the tokens it uses, so a
            50,000-token prompt costs more than a 12-token one.
          </p>
          <div className="h-actions">
            <DashboardButton big />
            <a className="h-btn h-btn-ghost h-btn-big" href={`${GITHUB}#quick-start-5-minutes`} rel="noreferrer">
              Read the quick start
            </a>
          </div>
          <div className="h-install">
            <code>{INSTALL}</code>
            <button type="button" className="h-copy" onClick={copy} aria-live="polite">
              {copyLabel(copyState, "Copy command")}
            </button>
          </div>
        </div>
        <HeroScene />
      </div>
    </section>
  );
}

function CostBars() {
  return (
    <figure className="bars">
      <div className="bar-row">
        <div className="bar-label">
          <span>Say hello</span>
          <span>12 tokens</span>
        </div>
        <div className="bar-track">
          <div className="bar-fill bar-small" style={{ width: "0.4%" }} />
        </div>
      </div>
      <div className="bar-row">
        <div className="bar-label">
          <span>Summarise a 90-page contract</span>
          <span>48,000 tokens</span>
        </div>
        <div className="bar-track">
          <div className="bar-fill bar-large" style={{ width: "100%" }} />
        </div>
      </div>
      <figcaption>
        Two example requests. A limiter that counts calls sees both as one, so one user can spend the whole budget in a
        few requests.
      </figcaption>
    </figure>
  );
}

function How() {
  return (
    <section id="how" className="h-section h-cream">
      <div className="h-wrap h-split">
        <div>
          <h2>Charge for what a request costs</h2>
          <p>
            A call to a language model can cost ten tokens or a hundred thousand, and the provider bills you for
            every one of them. tokenguard spends from a bucket of tokens instead of counting calls.
          </p>
          <ul className="h-list">
            <li>
              <b>Estimate before the call.</b> The charge is a guess from the size of the prompt, so a request that
              cannot fit is refused before it reaches the model.
            </li>
            <li>
              <b>Settle after it.</b> When the response reports the real usage, the difference is refunded or charged.
            </li>
            <li>
              <b>Cap the day and the month.</b> Each key can have daily and monthly budgets in tokens and dollars,
              with a callback when it passes 80%.
            </li>
          </ul>
        </div>
        <CostBars />
      </div>
    </section>
  );
}

function Install() {
  const [copyState, copy] = useCopy(SNIPPET);
  return (
    <section id="install" className="h-section h-navy">
      <div className="h-wrap h-split h-split-code">
        <div>
          <h2>Add it to a Django project</h2>
          <p>
            Install the package, add the middleware to limit every request, and put <code>@rate_limit</code> on any
            view that needs its own rule. You need Redis, Python 3.10 or newer, and Django 4.2 or 5.2.
          </p>
          <p>
            <a className="h-link" href={`${GITHUB}#quick-start-5-minutes`} rel="noreferrer">
              Follow the five-minute quick start
            </a>
          </p>
        </div>
        <div className="code">
          <button type="button" className="h-copy code-copy" onClick={copy} aria-live="polite">
            {copyLabel(copyState, "Copy code")}
          </button>
          <pre tabIndex={0}>
            <code>{SNIPPET}</code>
          </pre>
        </div>
      </div>
    </section>
  );
}

function Numbers() {
  return (
    <section id="numbers" className="h-section h-cream">
      <div className="h-wrap">
        <h2>What we measured</h2>
        <p>Each figure names the test it came from. The repository has the commands to repeat them on your own machine.</p>
        <dl className="facts">
          <div>
            <dt>0.89 ms</dt>
            <dd>
              What the limiter adds to each request with buffered metrics, down from 1.59 ms. Load test with 50 users on
              a 4-core Windows laptop, Redis in Docker.
            </dd>
          </div>
          <div>
            <dt>100 of 100</dt>
            <dd>
              Requests allowed against a limit of 100 when 8 processes hit one bucket at once. A version that reads, then
              writes, let through 318 to 354 of 400 in the same test (one Linux machine, Redis 7).
            </dd>
          </div>
          <div>
            <dt>112–128 bytes</dt>
            <dd>
              Redis memory per caller for the token bucket and fixed window, at any limit. The sliding window grows with
              the limit: about 6 KB at 100 and 1.3 MB at 10,000.
            </dd>
          </div>
        </dl>
        <p className="h-note">
          Read{" "}
          <a href={docs("algorithm-benchmarks.md")} rel="noreferrer">
            the benchmark methods and raw results
          </a>{" "}
          and{" "}
          <a href={docs("race-condition.md")} rel="noreferrer">
            the race test
          </a>
          .
        </p>
      </div>
    </section>
  );
}

export function Footer() {
  return (
    <footer className="h-footer h-navy">
      <div className="h-wrap h-footer-grid">
        <div>
          <h2>Watch it on live traffic</h2>
          <p>
            The dashboard shows every decision as it happens, and lets you change a limit or an algorithm while requests
            keep flowing.
          </p>
          <DashboardButton big />
        </div>
        <ul className="h-links">
          <li>
            <a href={GITHUB} rel="noreferrer">
              Source on GitHub
            </a>
          </li>
          <li>
            <a href={PYPI} rel="noreferrer">
              Package on PyPI
            </a>
          </li>
          <li>
            <a href={`${GITHUB}/blob/main/CHANGELOG.md`} rel="noreferrer">
              Changelog
            </a>
          </li>
          <li>
            <a href={`${GITHUB}/issues`} rel="noreferrer">
              Report a problem
            </a>
          </li>
          <li>
            <a href={routeHref(PRIVACY)}>Privacy</a>
          </li>
          <li>
            <a href={routeHref(TERMS)}>Terms and license</a>
          </li>
        </ul>
      </div>
    </footer>
  );
}

export function Home() {
  return (
    <div className="home">
      <a className="skip" href="#main">
        Skip to content
      </a>
      <Header />
      <main id="main" tabIndex={-1}>
        <Hero />
        <How />
        <Install />
        <Numbers />
      </main>
      <Footer />
    </div>
  );
}
