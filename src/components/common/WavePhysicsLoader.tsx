import React, { useEffect, useMemo, useState } from 'react';

const BAR_COUNT = 15;
const BAR_WIDTH = 12;
const BAR_GAP = 8;
const PERIOD_SECONDS = 4;
const BOUNCES = 4;
const BASE_HEIGHT = 16;
const PEAK_HEIGHT = 48;
const MAX_BOUNCE_HEIGHT = 60;

const calculateWavePhysics = (elapsedSeconds: number) => {
  const t = (((elapsedSeconds % PERIOD_SECONDS) + PERIOD_SECONDS) % PERIOD_SECONDS) / PERIOD_SECONDS;
  const xFraction = t < 0.5 ? t / 0.5 : (1 - t) / 0.5;
  const ballIndex = xFraction * (BAR_COUNT - 1);
  const bounceFraction = xFraction === 0 || xFraction === 1 ? 0 : (xFraction * BOUNCES) % 1;
  const bounceHeight = 4 * bounceFraction * (1 - bounceFraction);
  const heightFactor = Math.max(0, 1 - bounceHeight * 2);
  const ballY = BASE_HEIGHT + PEAK_HEIGHT - heightFactor * 20 + bounceHeight * MAX_BOUNCE_HEIGHT;
  const lerp = (from: number, to: number, amount: number) => Math.round(from + (to - from) * amount);
  const bars = Array.from({ length: BAR_COUNT }, (_, index) => {
    const distance = Math.abs(index - ballIndex);
    const wave = distance < 3 ? Math.cos((distance / 3) * (Math.PI / 2)) : 0;
    const indent = distance < 1.5 ? Math.cos((distance / 1.5) * (Math.PI / 2)) * heightFactor * 20 : 0;
    const height = Math.max(4, BASE_HEIGHT + wave * PEAK_HEIGHT - indent);
    const color = `rgb(${lerp(22, 201, wave)}, ${lerp(28, 162, wave)}, ${lerp(44, 74, wave)})`;
    return { height, color };
  });

  return {
    bars,
    ballX: ballIndex * (BAR_WIDTH + BAR_GAP),
    ballY,
    scaleX: 1 + heightFactor * 0.25,
    scaleY: 1 - heightFactor * 0.3,
  };
};

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

  const physics = useMemo(() => calculateWavePhysics(phase), [phase]);

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
