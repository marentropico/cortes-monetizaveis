import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";

export const SceneCyberpunkHUD: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Glitch RGB offset based on frame oscillation
  const glitchOffset = Math.sin(frame * 1.5) * (frame % 4 === 0 ? 8 : 2);
  const glitchY = frame % 6 === 0 ? (frame % 2 === 0 ? -4 : 4) : 0;

  // HUD Rings rotation
  const ringRotation = (frame * 4) % 360;
  const counterRotation = -(frame * 2.5) % 360;

  // Scale in spring
  const scale = spring({
    frame,
    fps,
    config: { damping: 14, stiffness: 150 },
  });

  // Typing effect on code tag
  const fullText = "<OLÁ_MUNDO />";
  const charCount = Math.floor(interpolate(frame, [0, 18], [1, fullText.length], {
    extrapolateRight: "clamp",
  }));
  const displayedText = fullText.substring(0, charCount);
  const showCursor = frame % 6 < 3;

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        backgroundColor: "#02040a",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontFamily: "'Courier New', 'Fira Code', monospace",
        overflow: "hidden",
        position: "relative",
      }}
    >
      {/* Sci-Fi Perspective Grid Floor */}
      <div
        style={{
          position: "absolute",
          inset: "-50% -50% 0 -50%",
          backgroundImage:
            "linear-gradient(rgba(0, 243, 255, 0.15) 1px, transparent 1px), linear-gradient(90deg, rgba(255, 0, 85, 0.15) 1px, transparent 1px)",
          backgroundSize: "40px 40px",
          transform: "perspective(400px) rotateX(65deg) translateY(20%)",
          opacity: 0.7,
        }}
      />

      {/* Rotating Outer HUD Ring */}
      <svg
        style={{
          position: "absolute",
          width: 580,
          height: 580,
          transform: `rotate(${ringRotation}deg)`,
          opacity: 0.45,
        }}
        viewBox="0 0 400 400"
      >
        <circle
          cx="200"
          cy="200"
          r="180"
          fill="none"
          stroke="#00f3ff"
          strokeWidth="1.5"
          strokeDasharray="15 30 5 10 40 10"
        />
        <circle
          cx="200"
          cy="200"
          r="160"
          fill="none"
          stroke="#ff0055"
          strokeWidth="1"
          strokeDasharray="6 12"
        />
      </svg>

      {/* Rotating Inner Counter-Ring */}
      <svg
        style={{
          position: "absolute",
          width: 440,
          height: 440,
          transform: `rotate(${counterRotation}deg)`,
          opacity: 0.5,
        }}
        viewBox="0 0 300 300"
      >
        <circle
          cx="150"
          cy="150"
          r="130"
          fill="none"
          stroke="#00f3ff"
          strokeWidth="2"
          strokeDasharray="20 40 80 40"
        />
      </svg>

      {/* Top Left Telemetry Readout */}
      <div
        style={{
          position: "absolute",
          top: 40,
          left: 48,
          color: "#00f3ff",
          fontSize: 13,
          lineHeight: 1.6,
          opacity: 0.75,
          textShadow: "0 0 8px rgba(0,243,255,0.6)",
        }}
      >
        <div>SYS_CORE: VIRTUAL_RENDERER_ACTIVE</div>
        <div>MEM_ALLOC: 0x7FFF94B2E0</div>
        <div>FRAME_TIME: {(frame * 33.33).toFixed(1)}ms</div>
        <div>CHROMATIC_SPLIT: ENABLED</div>
      </div>

      {/* Top Right Target Lock */}
      <div
        style={{
          position: "absolute",
          top: 40,
          right: 48,
          color: "#ff0055",
          fontSize: 13,
          textAlign: "right",
          lineHeight: 1.6,
          opacity: 0.85,
          textShadow: "0 0 8px rgba(255,0,85,0.6)",
        }}
      >
        <div>TARGET: [OLÁ_MUNDO]</div>
        <div>STATUS: LOCKED 100%</div>
        <div>GPS: 23°33'S 46°38'W</div>
      </div>

      {/* Center Holographic Glitch Container */}
      <div
        style={{
          position: "relative",
          zIndex: 10,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 14,
          transform: `scale(${scale})`,
        }}
      >
        {/* Cyberpunk Badge */}
        <div
          style={{
            backgroundColor: "rgba(0, 243, 255, 0.15)",
            border: "1px solid #00f3ff",
            color: "#00f3ff",
            padding: "4px 18px",
            fontSize: 13,
            letterSpacing: "0.25em",
            fontWeight: 800,
            textShadow: "0 0 10px #00f3ff",
            boxShadow: "0 0 20px rgba(0, 243, 255, 0.3)",
          }}
        >
          04 // CYBERPUNK HUD TERMINAL
        </div>

        {/* Chromatic Glitch Main Text */}
        <div
          style={{
            position: "relative",
            fontSize: 84,
            fontWeight: 900,
            letterSpacing: "-0.02em",
          }}
        >
          {/* Red/Magenta Offset Glitch Layer */}
          <div
            style={{
              position: "absolute",
              top: glitchY,
              left: -glitchOffset,
              color: "#ff0055",
              opacity: 0.85,
              mixBlendMode: "screen",
              whiteSpace: "nowrap",
            }}
          >
            {displayedText}
            {showCursor ? "_" : " "}
          </div>

          {/* Cyan Offset Glitch Layer */}
          <div
            style={{
              position: "absolute",
              top: -glitchY,
              left: glitchOffset,
              color: "#00f3ff",
              opacity: 0.85,
              mixBlendMode: "screen",
              whiteSpace: "nowrap",
            }}
          >
            {displayedText}
            {showCursor ? "_" : " "}
          </div>

          {/* Main White Layer */}
          <div
            style={{
              color: "#ffffff",
              textShadow: "0 0 25px rgba(0, 243, 255, 0.9)",
              position: "relative",
              whiteSpace: "nowrap",
            }}
          >
            {displayedText}
            {showCursor ? "_" : " "}
          </div>
        </div>

        {/* Telemetry subline */}
        <div
          style={{
            color: "rgba(255, 255, 255, 0.6)",
            fontSize: 16,
            letterSpacing: "0.15em",
            textTransform: "uppercase",
          }}
        >
          EXEC: remotion.render(target="production")
        </div>
      </div>
    </div>
  );
};
