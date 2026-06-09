export function Placeholder({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="panel">
      <div className="placeholder">
        <h2>{title}</h2>
        <p>{detail}</p>
      </div>
    </div>
  );
}
