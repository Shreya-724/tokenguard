import { Footer, GITHUB, Header } from "./Home.jsx";
import { PRIVACY } from "../lib/route.js";

const UPDATED = "7 November 2026";

function Privacy() {
  return (
    <>
      <h1>Privacy</h1>
      <p className="legal-meta">Last updated {UPDATED}</p>
      <p>
        This describes what the tokenguard home page and dashboard do with your information. tokenguard itself is
        open-source software that you run on your own servers; the project does not operate a hosted service.
      </p>

      <h2>The home page</h2>
      <p>
        It collects nothing. It has no analytics, no advertising, no cookies and no accounts, and it loads no scripts,
        fonts or images from other sites. The only time it uses your clipboard is when you press a copy button. Links to
        GitHub and PyPI lead to other sites with their own policies.
      </p>

      <h2>The dashboard</h2>
      <p>
        The dashboard is for staff of the site that hosts it. When you sign in, that site's server sets a session cookie
        and a CSRF cookie. Sign-in needs both, and the page stores nothing else in your browser.
      </p>
      <p>
        Once you are signed in, the dashboard shows traffic data held in that server's Redis: rule names, client IP
        addresses or hashed API keys, and counts of requests and tokens. Everyone with staff access can see it.
      </p>

      <h2>If you use the library</h2>
      <p>
        tokenguard keeps one counter per caller in your Redis: the caller's identity (a user id, an IP address, or a
        hash of an API key), a token balance and timestamps. Counters expire on their own, and metrics are kept for one
        hour by default (<code>METRICS_RETENTION</code>). If you run tokenguard for real users, you decide what is
        collected and you are responsible for telling those users about it.
      </p>

      <h2>Contact</h2>
      <p>
        Ask a question or report a problem by opening an issue at{" "}
        <a href={`${GITHUB}/issues`} rel="noreferrer">
          the project's GitHub page
        </a>
        .
      </p>
    </>
  );
}

function Terms() {
  return (
    <>
      <h1>Terms and license</h1>
      <p className="legal-meta">Last updated {UPDATED}</p>
      <p>
        tokenguard is released under the MIT license. You may use, copy, modify and distribute it, including in
        commercial work, as long as you keep the copyright notice and license text. The full text is in{" "}
        <a href={`${GITHUB}/blob/main/LICENSE`} rel="noreferrer">
          the LICENSE file
        </a>
        .
      </p>

      <h2>No warranty</h2>
      <p>
        The software is provided as is, without warranty of any kind. The authors are not liable for any claim or
        damages arising from its use.
      </p>

      <h2>Not a service</h2>
      <p>
        This page and its dashboard are a demonstration of the software. There is no hosted service, no uptime
        promise and no support agreement. The numbers shown on the home page come from the tests described in the
        repository and will differ on your hardware.
      </p>

      <h2>Rate limiting is one layer</h2>
      <p>
        A rate limiter reduces abuse; it does not make a service safe by itself. The README's security section lists
        what tokenguard does and does not protect against. You are responsible for how you deploy and configure it.
      </p>

      <h2>Other software</h2>
      <p>
        tokenguard builds on Redis, Django, React and other projects, each under its own license.
      </p>

      <p className="legal-note">
        This is a plain-language description, not legal advice. If you run tokenguard in front of real users, get your
        own terms and privacy policy.
      </p>
    </>
  );
}

export function Legal({ page }) {
  return (
    <div className="home">
      <a className="skip" href="#main">
        Skip to content
      </a>
      <Header minimal />
      <main id="main" tabIndex={-1} className="h-cream legal">
        <div className="h-wrap">
          <div className="legal-body">{page === PRIVACY ? <Privacy /> : <Terms />}</div>
        </div>
      </main>
      <Footer />
    </div>
  );
}
