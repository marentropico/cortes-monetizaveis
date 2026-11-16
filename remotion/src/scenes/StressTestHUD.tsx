import React from "react";
import { interpolate, useCurrentFrame, useVideoConfig } from "remotion";

export const StressTestHUD: React.FC = () => {
  const frame = useCurrentFrame();
  const { durationInFrames, fps } = useVideoConfig();

  const progress = interpolate(frame, [0, durationInFrames], [0, 100], {
    extrapolateRight: "clamp",
  });

  const currentTimeSeconds = (frame / fps).toFixed(2);
  const totalSeconds = (durationInFrames / fps).toFixed(2);

  // Determine current active style based on frame
  let activeStyle = "1/5 APPLE LIQUID GLASS";
  let activeColor = "#007aff";
  if (frame >= 30 && frame < 60) {
    activeStyle = "2/5 PUNK ZINE COLLAGE";
    activeColor = "#ffe600";
  } else if (frame >= 60 && frame < 90) {
    activeStyle = "3/5 BROADCAST NEWS";
    activeColor = "#d90429";
  } else if (frame >= 90 && frame < 120) {
    activeStyle = "4/5 CYBERPUNK HUD";
    activeColor = "#00f3ff";
  } else if (frame >= 120) {
    activeStyle = "5/5 ACID POP CLIMAX";
    activeColor = "#ccff00";
  }

  return (
    <div
      style={{
        position: "absolute",
        top: 0,
        left: 0,
        right: 0,
        zIndex: 100,
        pointerEvents: "none",
        fontFamily: "'Courier New', 'Fira Code', monospace",
      }}
    >
      {/* Top Telemetry Header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "16px 36px",
          backgroundColor: "rgba(0, 0, 0, 0.45)",
          backdropFilter: "blur(12px)",
          borderBottom: "1px solid rgba(255, 255, 255, 0.15)",
          color: "#ffffff",
          fontSize: 14,
          letterSpacing: "0.1em",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span
            style={{
              display: "inline-block",
              width: 10,
              height: 10,
              borderRadius: "50%",
              backgroundColor: activeColor,
              boxShadow: `0 0 10px ${activeColor}`,
            }}
          />
          <span style={{ fontWeight: 800 }}>REMOTION STRESS TEST</span>
          <span style={{ color: "rgba(255,255,255,0.4)" }}>|</span>
          <span style={{ color: activeColor, fontWeight: 700 }}>{activeStyle}</span>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
          <span>
            TIME: <strong style={{ color: "#ffffff" }}>{currentTimeSeconds}s</strong> / {totalSeconds}s
          </span>
          <span style={{ color: "rgba(255,255,255,0.4)" }}>|</span>
          <span>
            FRAME: <strong style={{ color: "#ffffff" }}>{frame}</strong> / {durationInFrames}
          </span>
          <span style={{ color: "rgba(255,255,255,0.4)" }}>|</span>
          <span>30 FPS @ 1080P</span>
        </div>
      </div>

      {/* Progress Bar with 5 style tick notches */}
      <div
        style={{
          width: "100%",
          height: 4,
          backgroundColor: "rgba(255, 255, 255, 0.15)",
          position: "relative",
        }}
      >
        <div
          style={{
            height: "100%",
            width: `${progress}%`,
            backgroundColor: activeColor,
            boxShadow: `0 0 12px ${activeColor}`,
            transition: "background-color 0.1s ease",
          }}
        />

        {/* 5 Tick Marks */}
        {[20, 40, 60, 80].map((notch) => (
          <div
            key={notch}
            style={{
              position: "absolute",
              left: `${notch}%`,
              top: 0,
              width: 2,
              height: 4,
              backgroundColor: "rgba(255, 255, 255, 0.5)",
            }}
          />
        ))}
      </div>
    </div>
  );
};
