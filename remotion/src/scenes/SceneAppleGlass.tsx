import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";

export const SceneAppleGlass: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Spring entrance for main card
  const cardScale = spring({
    frame,
    fps,
    config: { damping: 15, stiffness: 120, mass: 0.8 },
  });

  const cardOpacity = interpolate(frame, [0, 8], [0, 1], {
    extrapolateRight: "clamp",
  });

  // Floating background gradient orbs (trigonometric deterministic motion)
  const orb1X = Math.sin(frame / 12) * 60;
  const orb1Y = Math.cos(frame / 15) * 40;
  const orb2X = Math.cos(frame / 10) * 80;
  const orb2Y = Math.sin(frame / 14) * 50;

  // Shimmer reflection moving across glass
  const shimmerPos = interpolate(frame, [5, 25], [-120, 180], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Staggered letter animation for "Olá Mundo"
  const title = "Olá Mundo";
  const letters = title.split("");

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        backgroundColor: "#05070f",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontFamily:
          "-apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Inter', sans-serif",
        overflow: "hidden",
        position: "relative",
      }}
    >
      {/* Dynamic blurred mesh gradient orbs */}
      <div
        style={{
          position: "absolute",
          width: 500,
          height: 500,
          borderRadius: "50%",
          background: "radial-gradient(circle, rgba(0, 122, 255, 0.45) 0%, rgba(0, 122, 255, 0) 70%)",
          filter: "blur(60px)",
          transform: `translate(${orb1X - 100}px, ${orb1Y - 80}px)`,
        }}
      />
      <div
        style={{
          position: "absolute",
          width: 450,
          height: 450,
          borderRadius: "50%",
          background: "radial-gradient(circle, rgba(175, 82, 222, 0.4) 0%, rgba(175, 82, 222, 0) 70%)",
          filter: "blur(60px)",
          transform: `translate(${orb2X + 120}px, ${orb2Y + 60}px)`,
        }}
      />
      <div
        style={{
          position: "absolute",
          width: 400,
          height: 400,
          borderRadius: "50%",
          background: "radial-gradient(circle, rgba(255, 149, 0, 0.35) 0%, rgba(255, 149, 0) 0%)",
          filter: "blur(70px)",
          transform: `translate(${-orb2X + 50}px, ${-orb1Y + 120}px)`,
        }}
      />

      {/* Sleek Apple-style Frosted Glass Card */}
      <div
        style={{
          position: "relative",
          zIndex: 10,
          padding: "50px 80px",
          borderRadius: 36,
          background:
            "linear-gradient(135deg, rgba(255, 255, 255, 0.12) 0%, rgba(255, 255, 255, 0.03) 100%)",
          backdropFilter: "blur(40px) saturate(180%)",
          WebkitBackdropFilter: "blur(40px) saturate(180%)",
          border: "1px solid rgba(255, 255, 255, 0.22)",
          boxShadow:
            "0 30px 60px rgba(0, 0, 0, 0.5), inset 0 1px 1px rgba(255, 255, 255, 0.35)",
          transform: `scale(${cardScale})`,
          opacity: cardOpacity,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 16,
          overflow: "hidden",
        }}
      >
        {/* Shimmer light sweep */}
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            width: "50%",
            height: "100%",
            background:
              "linear-gradient(90deg, transparent, rgba(255,255,255,0.18), transparent)",
            transform: `skewX(-25deg) translateX(${shimmerPos}%)`,
            pointerEvents: "none",
          }}
        />

        {/* Style Badge */}
        <div
          style={{
            fontSize: 13,
            letterSpacing: "0.22em",
            textTransform: "uppercase",
            color: "rgba(255, 255, 255, 0.7)",
            padding: "6px 16px",
            borderRadius: 20,
            background: "rgba(255, 255, 255, 0.08)",
            border: "1px solid rgba(255, 255, 255, 0.15)",
            fontWeight: 600,
          }}
        >
          01 // Apple Liquid Glass
        </div>

        {/* Main Title with Staggered Kinetic Letters */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 88,
            fontWeight: 700,
            letterSpacing: "-0.03em",
            color: "#ffffff",
            textShadow: "0 10px 30px rgba(0, 0, 0, 0.5)",
          }}
        >
          {letters.map((char, i) => {
            const letterDelay = i * 1.5;
            const letterSpring = spring({
              frame: frame - letterDelay,
              fps,
              config: { damping: 12, stiffness: 140 },
            });
            const letterOpacity = interpolate(
              frame - letterDelay,
              [0, 5],
              [0, 1],
              { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
            );

            return (
              <span
                key={i}
                style={{
                  display: "inline-block",
                  transform: `translateY(${(1 - letterSpring) * 30}px) scale(${letterSpring})`,
                  opacity: letterOpacity,
                  whiteSpace: char === " " ? "pre" : "normal",
                  background:
                    "linear-gradient(180deg, #FFFFFF 30%, rgba(255,255,255,0.7) 100%)",
                  WebkitBackgroundClip: "text",
                  WebkitTextFillColor: "transparent",
                }}
              >
                {char}
              </span>
            );
          })}
        </div>

        {/* Minimal subtitle */}
        <div
          style={{
            fontSize: 18,
            fontWeight: 400,
            color: "rgba(255, 255, 255, 0.6)",
            letterSpacing: "0.05em",
          }}
        >
          Renderizado programático com Remotion
        </div>
      </div>
    </div>
  );
};
