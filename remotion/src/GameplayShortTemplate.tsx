import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";

export interface GameplayWord {
  word: string;
  start: number;
  end: number;
}

export interface GameplayShortTemplateProps {
  title?: string;
  hookText?: string;
  durationType?: "30s" | "60s" | "90s";
  accentColor?: string;
  words?: GameplayWord[];
}

export const GameplayShortTemplate: React.FC<GameplayShortTemplateProps> = ({
  title = "CLUTCH INSANO",
  hookText = "OLHA O QUE ACONTECEU AQUI!",
  durationType = "30s",
  accentColor = "#00E6FF",
  words = [
    { word: "OLHA", start: 0.2, end: 0.6 },
    { word: "ESSA", start: 0.6, end: 1.0 },
    { word: "JOGADA", start: 1.0, end: 1.6 },
    { word: "ABSURDA!", start: 1.6, end: 2.4 },
  ],
}) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const currentSec = frame / fps;

  const hookEntrance = spring({
    frame,
    fps,
    config: { damping: 14, stiffness: 150, mass: 0.8 },
  });

  const hookOpacity = interpolate(
    frame,
    [0, 8, Math.min(95, durationInFrames - 15), Math.min(110, durationInFrames)],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  const progress = interpolate(frame, [0, durationInFrames], [0, 100], {
    extrapolateRight: "clamp",
  });

  return (
    <div
      style={{
        width: 1080,
        height: 1920,
        backgroundColor: "#060913",
        position: "relative",
        overflow: "hidden",
        fontFamily: "'Arial Black', 'Impact', sans-serif",
      }}
    >
      {/* Top 1/3 Facecam Zone (1080x640) */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          width: 1080,
          height: 640,
          background:
            "radial-gradient(circle at 50% 45%, rgba(0,230,255,0.18), rgba(6,9,19,0.96) 72%)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "rgba(255,255,255,0.55)",
          fontSize: 28,
          letterSpacing: "0.14em",
        }}
      >
        FACECAM ZONE (1080x640)
      </div>

      {/* Bottom 2/3 Gameplay Zone (1080x1280) */}
      <div
        style={{
          position: "absolute",
          top: 640,
          left: 0,
          width: 1080,
          height: 1280,
          background:
            "linear-gradient(180deg, #0b1224 0%, #05070f 65%, #0a1020 100%)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "rgba(255,255,255,0.35)",
          fontSize: 30,
          letterSpacing: "0.14em",
        }}
      >
        GAMEPLAY ZONE (1080x1280)
      </div>

      {/* Glowing Split-Screen Divider */}
      <div
        style={{
          position: "absolute",
          top: 636,
          left: 0,
          width: 1080,
          height: 8,
          backgroundColor: accentColor,
          boxShadow: `0 0 24px ${accentColor}`,
        }}
      />

      {/* Duration & Title Badge */}
      <div
        style={{
          position: "absolute",
          top: 608,
          right: 36,
          backgroundColor: "#0f172a",
          border: `2px solid ${accentColor}`,
          color: "#ffffff",
          padding: "8px 18px",
          borderRadius: 999,
          fontSize: 20,
          letterSpacing: "0.08em",
        }}
      >
        {durationType.toUpperCase()} • {title}
      </div>

      {/* Animated Hook Banner (first 3.5s) */}
      <div
        style={{
          position: "absolute",
          top: 90,
          left: 60,
          right: 60,
          display: "flex",
          justifyContent: "center",
          transform: `scale(${hookEntrance})`,
          opacity: hookOpacity,
        }}
      >
        <div
          style={{
            backgroundColor: "rgba(0, 0, 0, 0.84)",
            border: `3px solid ${accentColor}`,
            borderRadius: 20,
            padding: "18px 34px",
            color: "#FFE600",
            fontSize: 44,
            textAlign: "center",
            textShadow: "0 4px 12px rgba(0,0,0,0.9)",
          }}
        >
          {hookText}
        </div>
      </div>

      {/* Dynamic Word-by-Word Captions */}
      <div
        style={{
          position: "absolute",
          bottom: 320,
          left: 60,
          right: 60,
          display: "flex",
          flexWrap: "wrap",
          justifyContent: "center",
          gap: 18,
        }}
      >
        {words.map((item, idx) => {
          const isActive = currentSec >= item.start && currentSec <= item.end;
          return (
            <span
              key={`${item.word}-${idx}`}
              style={{
                fontSize: 66,
                color: isActive ? "#FFE600" : "#FFFFFF",
                transform: isActive ? "scale(1.16)" : "scale(1)",
                textShadow:
                  "-4px -4px 0 #000, 4px -4px 0 #000, -4px 4px 0 #000, 4px 4px 0 #000",
              }}
            >
              {item.word}
            </span>
          );
        })}
      </div>

      {/* Bottom Progress Bar */}
      <div
        style={{
          position: "absolute",
          bottom: 0,
          left: 0,
          width: "100%",
          height: 10,
          backgroundColor: "rgba(255,255,255,0.12)",
        }}
      >
        <div
          style={{
            height: "100%",
            width: `${progress}%`,
            backgroundColor: accentColor,
          }}
        />
      </div>
    </div>
  );
};
