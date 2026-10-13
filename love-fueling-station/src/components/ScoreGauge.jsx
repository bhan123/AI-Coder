const clampScore = (score) => Math.max(0, Math.min(100, score));

export function ScoreGauge({ score, status }) {
  const safeScore = clampScore(score);
  const angle = -135 + safeScore * 2.7;

  return (
    <section className="gauge-wrap" aria-label={`当前爱意温度 ${safeScore} 分，${status}`}>
      <div className="gauge" style={{ '--needle-angle': `${angle}deg`, '--score': safeScore }}>
        <div className="gauge-track" />
        <div className="gauge-progress" />
        <div className="gauge-spark" />
        <div className="gauge-value">
          <strong>{safeScore}</strong>
          <span>{status}</span>
        </div>
      </div>
      <p className="gauge-copy"><span>♧</span> 平凡日子，也要用心</p>
    </section>
  );
}
