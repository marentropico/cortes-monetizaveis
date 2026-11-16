import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";

export const SceneAcidPopClimax: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Squash and Stretch Spring Physics
  const bounceSpring = spring({
    frame,
    fps,
    config: { damping: 8, stiffness: 200, mass: 0.6 },
  });

  // Squash/stretch oscillation
  const scaleX = interpolate(bounceSpring, [0, 0.7, 1], [0.3, 1.15, 1]);
  const scaleY = interpolate(bounceSpring, [0, 0.7, 1], [1.4, 0.88, 1]);

  // Starburst rotation
  const bgRotation = (frame * 5) % 360;

  // Generate 50 deterministic confetti particles
  const particles = Array.from({ length: 50 }).map((_, i) => {
    const angle = (i * (360 / 50) * Math.PI) / 180;
    const speed = 250 + (i % 7) * 45;
    const size = 12 + (i % 5) * 6;
    const colors = ["#CCFF00", "#FF007F", "#00F0FF", "#FFE600", "#FFFFFF", "#000000"];
    const color = colors[i % colors.length];
    const isSquare = i % 2 === 0;

    // Expand outward with physics
    const progress = interpolate(frame, [0, 28], [0, 1], {
      extrapolateRight: "clamp",
    });

    // Gravity pull downward
    const posX = Math.cos(angle) * speed * progress;
    const posY = Math.sin(angle) * speed * progress + progress * progress * 150;
    const particleRot = (i * 30 + frame * 10) % 360;

    return {
      posX,
      posY,
      size,
      color,
      isSquare,
      particleRot,
    };
  });

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        backgroundColor: "#CCFF00",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontFamily: "'Arial Black', 'Impact', sans-serif",
        overflow: "hidden",
        position: "relative",
      }}
    >
      {/* Neo-brutalist animated diagonal stripes */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          backgroundImage:
            "repeating-linear-gradient(45deg, #CCFF00 0, #CCFF00 25px, #b8e600 25px, #b8e600 50px)",
        }}
      />

      {/* Rotating geometric starburst in background */}
      <div
        style={{
          position: "absolute",
          width: 900,
          height: 900,
          borderRadius: "50%",
          border: "4px dashed #000000",
          transform: `rotate(${bgRotation}deg)`,
          opacity: 0.35,
        }}
      />

      {/* Confetti Particle Explosion */}
      {particles.map((p, idx) => (
        <div
          key={idx}
          style={{
            position: "absolute",
            width: p.size,
            height: p.size,
            borderRadius: p.isSquare ? 2 : "50%",
            backgroundColor: p.color,
            border: "2px solid #000000",
            boxShadow: "3px 3px 0px #000000",
            transform: `translate(${p.posX}px, ${p.posY}px) rotate(${p.particleRot}deg)`,
            zIndex: 15,
          }}
        />
      ))}

      {/* Main Neo-Brutalist Sticker Card */}
      <div
        style={{
          position: "relative",
          zIndex: 20,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 16,
          transform: `scale(${scaleX}, ${scaleY})`,
        }}
      >
        {/* Top Floating Badge */}
        <div
          style={{
            backgroundColor: "#FF007F",
            color: "#FFFFFF",
            padding: "8px 24px",
            fontSize: 20,
            fontWeight: 900,
            letterSpacing: "0.15em",
            textTransform: "uppercase",
            border: "4px solid #000000",
            boxShadow: "6px 6px 0px #000000",
            transform: "rotate(-3deg)",
          }}
        >
          05 // ACID POP CLIMAX ★
        </div>

        {/* Big Impact Neo-Brutalist Title */}
        <div
          style={{
            backgroundColor: "#FFFFFF",
            color: "#000000",
            padding: "20px 50px",
            fontSize: 98,
            fontWeight: 900,
            letterSpacing: "-0.02em",
            border: "6px solid #000000",
            boxShadow: "14px 14px 0px #000000",
            transform: "rotate(1.5deg)",
            display: "flex",
            alignItems: "center",
            gap: 20,
          }}
        >
          <span>OLÁ MUNDO</span>
          <span style={{ color: "#FF007F" }}>★</span>
        </div>

        {/* Bottom Subtitle Badge */}
        <div
          style={{
            backgroundColor: "#00F0FF",
            color: "#000000",
            padding: "8px 26px",
            fontSize: 20,
            fontWeight: 900,
            letterSpacing: "0.1em",
            textTransform: "uppercase",
            border: "4px solid #000000",
            boxShadow: "5px 5px 0px #000000",
            transform: "rotate(-1deg)",
          }}
        >
          REMOTION STRESS TEST: 100% COMPLETE!
        </div>
      </div>
    </div>
  );
};
