export function Panel({ title, meta, children, className = "" }) {
  return (
    <section className={`panel ${className}`} aria-label={title}>
      <header className="panel-h">
        <h2>{title}</h2>
        {meta ? <div className="panel-meta">{meta}</div> : null}
      </header>
      <div className="panel-b">{children}</div>
    </section>
  );
}
