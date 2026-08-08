import React, { useEffect, useMemo, useState } from 'react';

export const WavePhysicsLoader: React.FC<{ scale?: number }> = ({ scale = 1 }) => {
  const [phase, setPhase] = useState(0);

  useEffect(() => {
    let frame = 0;
    const start = performance.now();
    const tick = (now: number) => {
      setPhase((now - start) / 1000);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, []);

  const physics = useMemo(() => {
    const t = (phase % 4) / 4;
    const xFrac = t < 0.5 ? t / 0.5 : (1 - t) / 0.5;
    const ballIndex = xFrac * 14;
    const bounceF = (xFrac * 4) % 1;
    const bounceH = 4 * bounceF * (1 - bounceF);
    const heightFactor = Math.max(0, 1 - bounceH * 2);
    const ballY = (16 + 48 - heightFactor * 20) + bounceH * 60;
    const bars = Array.from({ length: 15 }, (_, index) => {
      const distance = Math.abs(index - ballIndex);
      const wave = distance < 3 ? Math.cos((distance / 3) * Math.PI / 2) : 0;
      const indent = distance < 1.5 ? Math.cos((distance / 1.5) * Math.PI / 2) * heightFactor * 20 : 0;
      const height = Math.max(4, 16 + wave * 48 - indent);
      const r = Math.round(22 + wave * (201 - 22));
      const g = Math.round(28 + wave * (162 - 28));
      const b = Math.round(44 + wave * (74 - 44));
      return { height, color: `rgb(${r}, ${g}, ${b})` };
    });
    return { bars, ballX: ballIndex * 20, ballY, scaleX: 1 + heightFactor * 0.25, scaleY: 1 - heightFactor * 0.3 };
  }, [phase]);

  return (
    <section className="wave-loader" style={{ transform: `scale(${scale})` }} aria-label="載入中">
      <div className="wave-stage">
        {physics.bars.map((bar, index) => (
          <span className="wave-bar" key={index} style={{ left: index * 20, height: bar.height, background: bar.color }} />
        ))}
        <span
          className="wave-ball"
          style={{ left: physics.ballX, bottom: physics.ballY, transform: `scale(${physics.scaleX}, ${physics.scaleY})` }}
        />
      </div>
      <span className="wave-label">載入中…</span>
    </section>
  );
};
