import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";

export const JuliaBurnoutinho: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Gentle Spring Entrance for the main card (soft, non-aggressive, comforting)
  const cardEntrance = spring({
    frame,
    fps,
    config: { damping: 14, stiffness: 90, mass: 0.9 },
  });

  // Flower bloom spring
  const flowerBloom = spring({
    frame: frame - 6,
    fps,
    config: { damping: 11, stiffness: 100, mass: 0.8 },
  });

  // Calm floating/breathing motion (soothing organic wave)
  const floatY = Math.sin(frame / 16) * 12;
  const floatRot = Math.sin(frame / 20) * 2.5;

  // Blinking eyes animation (blinks around frame 65-72 and 130-137)
  const isBlinking =
    (frame >= 65 && frame <= 71) || (frame >= 128 && frame <= 134);

  // Soft falling sakura petals (16 deterministic petals floating down)
  const petals = Array.from({ length: 16 }).map((_, i) => {
    const seed = i * 73 + 17;
    const speed = 2.2 + (seed % 4) * 0.6;
    const startX = (seed * 89) % 1000 + 40;
    const wobbleSpeed = 14 + (seed % 6);
    const wobbleDist = 25 + (seed % 20);

    const x = startX + Math.sin((frame + seed) / wobbleSpeed) * wobbleDist;
    const y = ((frame * speed + seed * 120) % 2100) - 100;
    const rotation = (seed * 30 + frame * (1.2 + (seed % 3) * 0.3)) % 360;
    const size = 18 + (seed % 14);
    const opacity = 0.55 + (seed % 4) * 0.1;

    return { x, y, rotation, size, opacity };
  });

  // Sparkles around the flower
  const sparkles = [
    { top: -20, left: 40, delay: 0 },
    { top: 20, right: 30, delay: 10 },
    { bottom: 30, left: 30, delay: 20 },
    { top: 120, right: 10, delay: 15 },
  ];

  // Text entrance springs
  const text1Spring = spring({
    frame: frame - 16,
    fps,
    config: { damping: 13, stiffness: 110 },
  });

  const text2Spring = spring({
    frame: frame - 24,
    fps,
    config: { damping: 13, stiffness: 110 },
  });

  const text3Spring = spring({
    frame: frame - 32,
    fps,
    config: { damping: 13, stiffness: 110 },
  });

  return (
    <div
      style={{
        width: 1080,
        height: 1920,
        background:
          "linear-gradient(175deg, #FFE8EC 0%, #FFF5F7 35%, #F0EEFF 70%, #E8F4FD 100%)",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        fontFamily:
          "'Quicksand', 'Nunito', 'Comfortaa', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
        overflow: "hidden",
        position: "relative",
      }}
    >
      {/* Background soft glowing ambient pastel orbs */}
      <div
        style={{
          position: "absolute",
          top: "12%",
          left: "10%",
          width: 500,
          height: 500,
          borderRadius: "50%",
          background:
            "radial-gradient(circle, rgba(255, 182, 193, 0.45) 0%, rgba(255, 182, 193, 0) 70%)",
          filter: "blur(60px)",
          transform: `translate(${Math.sin(frame / 20) * 30}px, ${Math.cos(frame / 22) * 20}px)`,
        }}
      />
      <div
        style={{
          position: "absolute",
          bottom: "15%",
          right: "8%",
          width: 600,
          height: 600,
          borderRadius: "50%",
          background:
            "radial-gradient(circle, rgba(216, 210, 255, 0.45) 0%, rgba(216, 210, 255, 0) 70%)",
          filter: "blur(70px)",
          transform: `translate(${Math.cos(frame / 25) * -30}px, ${Math.sin(frame / 20) * -20}px)`,
        }}
      />

      {/* Floating Petals Layer */}
      {petals.map((petal, idx) => (
        <div
          key={idx}
          style={{
            position: "absolute",
            left: petal.x,
            top: petal.y,
            transform: `rotate(${petal.rotation}deg)`,
            opacity: petal.opacity,
            pointerEvents: "none",
            fontSize: petal.size,
            filter: "drop-shadow(0 4px 6px rgba(255, 150, 180, 0.25))",
          }}
        >
          🌸
        </div>
      ))}

      {/* Main Sweet Card Container */}
      <div
        style={{
          position: "relative",
          zIndex: 10,
          width: 880,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          transform: `scale(${cardEntrance}) translateY(${floatY}px) rotate(${floatRot}deg)`,
          padding: "60px 48px",
          borderRadius: 56,
          background: "rgba(255, 255, 255, 0.72)",
          backdropFilter: "blur(28px) saturate(140%)",
          border: "2px solid rgba(255, 255, 255, 0.95)",
          boxShadow:
            "0 30px 80px rgba(244, 143, 177, 0.22), 0 10px 30px rgba(0, 0, 0, 0.04), inset 0 2px 4px rgba(255, 255, 255, 0.8)",
        }}
      >
        {/* Soft Pill Badge: Lembrete com Carinho */}
        <div
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 10,
            padding: "10px 28px",
            borderRadius: 30,
            background: "linear-gradient(135deg, #FFE5EC 0%, #FFF0F3 100%)",
            border: "1.5px solid #FFCCD5",
            color: "#FF4D6D",
            fontSize: 22,
            fontWeight: 800,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            boxShadow: "0 6px 16px rgba(255, 77, 109, 0.12)",
            marginBottom: 36,
          }}
        >
          <span>🌸</span>
          <span>Lembrete com Carinho</span>
          <span>🌸</span>
        </div>

        {/* Central Kawaii Flower Avatar */}
        <div
          style={{
            position: "relative",
            width: 320,
            height: 320,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            transform: `scale(${flowerBloom})`,
            marginBottom: 36,
          }}
        >
          {/* Sparkles around flower */}
          {sparkles.map((s, index) => {
            const sparkleOpacity = interpolate(
              Math.sin((frame + s.delay) / 5),
              [-1, 1],
              [0.3, 1]
            );
            const sparkleScale = interpolate(
              Math.sin((frame + s.delay) / 5),
              [-1, 1],
              [0.75, 1.25]
            );

            return (
              <span
                key={index}
                style={{
                  position: "absolute",
                  top: s.top,
                  bottom: s.bottom,
                  left: s.left,
                  right: s.right,
                  fontSize: 34,
                  opacity: sparkleOpacity,
                  transform: `scale(${sparkleScale})`,
                  filter: "drop-shadow(0 2px 8px rgba(255, 215, 0, 0.6))",
                  pointerEvents: "none",
                }}
              >
                ✨
              </span>
            );
          })}

          {/* SVG Kawaii Flower with animated gentle swaying petals & blushing smile */}
          <svg
            viewBox="0 0 200 200"
            style={{
              width: "100%",
              height: "100%",
              filter: "drop-shadow(0 18px 24px rgba(255, 138, 166, 0.32))",
            }}
          >
            {/* 8 Soft Petals */}
            {[0, 45, 90, 135, 180, 225, 270, 315].map((angle, i) => {
              const petalPulse = 1 + Math.sin((frame + i * 8) / 12) * 0.05;
              return (
                <g key={angle} transform={`rotate(${angle} 100 100)`}>
                  <ellipse
                    cx="100"
                    cy="44"
                    rx={25 * petalPulse}
                    ry={36 * petalPulse}
                    fill="url(#petalGradient)"
                  />
                </g>
              );
            })}

            {/* Petal Gradient definition */}
            <defs>
              <linearGradient id="petalGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#FFAFCC" />
                <stop offset="60%" stopColor="#FFC8DD" />
                <stop offset="100%" stopColor="#FFDEE9" />
              </linearGradient>
              <radialGradient id="centerGradient" cx="50%" cy="40%" r="55%">
                <stop offset="0%" stopColor="#FFF9A6" />
                <stop offset="70%" stopColor="#FFE066" />
                <stop offset="100%" stopColor="#F4C430" />
              </radialGradient>
            </defs>

            {/* Glowing Center Core */}
            <circle
              cx="100"
              cy="100"
              r="48"
              fill="url(#centerGradient)"
              stroke="#FFF275"
              strokeWidth="3"
            />

            {/* Rosy Cheeks */}
            <ellipse
              cx="74"
              cy="114"
              rx="10"
              ry="6"
              fill="#FF6B8B"
              opacity="0.65"
            />
            <ellipse
              cx="126"
              cy="114"
              rx="10"
              ry="6"
              fill="#FF6B8B"
              opacity="0.65"
            />

            {/* Sweet Kawaii Eyes */}
            {isBlinking ? (
              // Closed smiling happy eyes (blink)
              <>
                <path
                  d="M 76 96 Q 84 90 92 96"
                  fill="none"
                  stroke="#4A2810"
                  strokeWidth="3.5"
                  strokeLinecap="round"
                />
                <path
                  d="M 108 96 Q 116 90 124 96"
                  fill="none"
                  stroke="#4A2810"
                  strokeWidth="3.5"
                  strokeLinecap="round"
                />
              </>
            ) : (
              // Big shiny anime eyes
              <>
                <circle cx="84" cy="95" r="7" fill="#4A2810" />
                <circle cx="82" cy="92.5" r="2.8" fill="#FFFFFF" />
                <circle cx="86" cy="96.5" r="1.4" fill="#FFFFFF" />

                <circle cx="116" cy="95" r="7" fill="#4A2810" />
                <circle cx="114" cy="92.5" r="2.8" fill="#FFFFFF" />
                <circle cx="118" cy="96.5" r="1.4" fill="#FFFFFF" />
              </>
            )}

            {/* Cute Smile */}
            <path
              d="M 93 107 Q 100 116 107 107"
              fill="none"
              stroke="#4A2810"
              strokeWidth="3.5"
              strokeLinecap="round"
            />
          </svg>
        </div>

        {/* Text 1: "Julia," */}
        <div
          style={{
            fontSize: 72,
            fontWeight: 900,
            color: "#4A1525",
            letterSpacing: "-0.02em",
            transform: `translateY(${(1 - text1Spring) * 25}px) scale(${text1Spring})`,
            opacity: text1Spring,
            marginBottom: 12,
            display: "flex",
            alignItems: "center",
            gap: 12,
          }}
        >
          <span>Julia,</span>
          <span style={{ fontSize: 56 }}>💖</span>
        </div>

        {/* Text 2: "cuidado com o burnoutinho" */}
        <div
          style={{
            fontSize: 48,
            fontWeight: 800,
            lineHeight: 1.25,
            textAlign: "center",
            color: "#592E3B",
            transform: `translateY(${(1 - text2Spring) * 25}px) scale(${text2Spring})`,
            opacity: text2Spring,
            padding: "16px 28px",
            borderRadius: 24,
            background:
              "linear-gradient(135deg, rgba(255, 230, 235, 0.85) 0%, rgba(255, 240, 245, 0.85) 100%)",
            border: "1.5px solid #FFD1DC",
            boxShadow: "0 8px 24px rgba(255, 140, 160, 0.15)",
            marginBottom: 28,
            width: "90%",
          }}
        >
          cuidado com o{" "}
          <span
            style={{
              color: "#E63946",
              fontWeight: 900,
              textDecoration: "underline wavy #FFAFCC 3px",
              textUnderlineOffset: 6,
            }}
          >
            burnoutinho
          </span>{" "}
          🥺
        </div>

        {/* Text 3: Soothing Advice Pill */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 12,
            padding: "16px 36px",
            borderRadius: 32,
            background: "#FFFFFF",
            border: "1.5px solid #E8DFF5",
            boxShadow: "0 10px 28px rgba(180, 160, 220, 0.18)",
            transform: `translateY(${(1 - text3Spring) * 20}px) scale(${text3Spring})`,
            opacity: text3Spring,
          }}
        >
          <span style={{ fontSize: 28 }}>☕</span>
          <span
            style={{
              fontSize: 24,
              fontWeight: 700,
              color: "#6D597A",
              letterSpacing: "0.02em",
            }}
          >
            Respira fundo & faz uma pausinha
          </span>
          <span style={{ fontSize: 28 }}>🍵</span>
        </div>
      </div>

      {/* Floating Bottom Reminder Heart */}
      <div
        style={{
          position: "absolute",
          bottom: 100,
          display: "flex",
          alignItems: "center",
          gap: 10,
          color: "#9A8C98",
          fontSize: 20,
          fontWeight: 600,
          letterSpacing: "0.08em",
          opacity: 0.85,
        }}
      >
        <span>Você é muito importante pra gente</span>
        <span style={{ color: "#FF758F" }}>♥</span>
      </div>
    </div>
  );
};
