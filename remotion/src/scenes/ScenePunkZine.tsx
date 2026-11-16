import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { noise2D } from "@remotion/noise";

export const ScenePunkZine: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Subtle punk camera wobble/jitter
  const jitterX = noise2D("punk-x", frame / 4, 0) * 8;
  const jitterY = noise2D("punk-y", 0, frame / 4) * 8;
  const jitterRot = noise2D("punk-rot", frame / 5, 0) * 2;

  // Stamped letters configuration (different colors, fonts, rotations like a ransom note)
  const letters = [
    { char: "O", bg: "#FFE600", color: "#000", rot: -6, font: "Impact, sans-serif" },
    { char: "L", bg: "#FF0055", color: "#FFF", rot: 8, font: "'Courier New', monospace" },
    { char: "Á", bg: "#00F0FF", color: "#000", rot: -4, font: "Arial Black, sans-serif" },
    { char: " ", bg: "transparent", color: "transparent", rot: 0, font: "sans-serif" },
    { char: "M", bg: "#FFFFFF", color: "#000", rot: 7, font: "Georgia, serif" },
    { char: "U", bg: "#FFE600", color: "#000", rot: -5, font: "Impact, sans-serif" },
    { char: "N", bg: "#FF0055", color: "#FFF", rot: 6, font: "'Courier New', monospace" },
    { char: "D", bg: "#000000", color: "#FFF", rot: -8, font: "Arial Black, sans-serif", border: "2px solid #FFE600" },
    { char: "O", bg: "#FFE600", color: "#000", rot: 5, font: "Impact, sans-serif" },
    { char: "!", bg: "#FF0055", color: "#FFF", rot: 12, font: "Impact, sans-serif" },
  ];

  const overallScale = spring({
    frame,
    fps,
    config: { damping: 10, stiffness: 180, mass: 0.5 },
  });

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        backgroundColor: "#18181b",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        overflow: "hidden",
        position: "relative",
        transform: `translate(${jitterX}px, ${jitterY}px) rotate(${jitterRot}deg)`,
      }}
    >
      {/* Halftone / Newsprint Grunge Background pattern */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          opacity: 0.25,
          backgroundImage:
            "radial-gradient(#ffffff 1.5px, transparent 1.5px), radial-gradient(#ffe600 1.5px, #18181b 1.5px)",
          backgroundSize: "24px 24px",
          backgroundPosition: "0 0, 12px 12px",
        }}
      />

      {/* Ripped Paper Backing with heavy drop shadow */}
      <div
        style={{
          position: "absolute",
          width: 900,
          height: 380,
          backgroundColor: "#f4f1ea",
          transform: "rotate(-1.5deg)",
          boxShadow: "14px 18px 0px #000000",
          border: "4px solid #000000",
        }}
      />

      {/* Scotch Tape Top Left */}
      <div
        style={{
          position: "absolute",
          top: "28%",
          left: "22%",
          width: 140,
          height: 40,
          backgroundColor: "rgba(255, 255, 255, 0.65)",
          transform: "rotate(-25deg)",
          boxShadow: "0 2px 6px rgba(0,0,0,0.15)",
          border: "1px dashed rgba(0,0,0,0.2)",
          zIndex: 20,
        }}
      />

      {/* Scotch Tape Bottom Right */}
      <div
        style={{
          position: "absolute",
          bottom: "30%",
          right: "23%",
          width: 150,
          height: 40,
          backgroundColor: "rgba(255, 255, 255, 0.65)",
          transform: "rotate(30deg)",
          boxShadow: "0 2px 6px rgba(0,0,0,0.15)",
          border: "1px dashed rgba(0,0,0,0.2)",
          zIndex: 20,
        }}
      />

      {/* Main Container */}
      <div
        style={{
          position: "relative",
          zIndex: 10,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 20,
          transform: `scale(${overallScale})`,
        }}
      >
        {/* Punk Badge */}
        <div
          style={{
            backgroundColor: "#000000",
            color: "#FFE600",
            padding: "8px 22px",
            fontSize: 22,
            fontFamily: "Impact, sans-serif",
            letterSpacing: "0.15em",
            textTransform: "uppercase",
            transform: "rotate(3deg)",
            boxShadow: "5px 5px 0px #FF0055",
          }}
        >
          02 // PUNK ZINE COLLAGE
        </div>

        {/* Ransom Note Letters */}
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            justifyContent: "center",
            alignItems: "center",
            gap: 12,
          }}
        >
          {letters.map((item, index) => {
            const letterDelay = index * 1.2;
            const letterDrop = spring({
              frame: frame - letterDelay,
              fps,
              config: { damping: 9, stiffness: 220, mass: 0.4 },
            });
            const letterY = interpolate(letterDrop, [0, 1], [-200, 0]);

            if (item.char === " ") {
              return <div key={index} style={{ width: 25 }} />;
            }

            return (
              <div
                key={index}
                style={{
                  backgroundColor: item.bg,
                  color: item.color,
                  fontFamily: item.font,
                  fontSize: 76,
                  fontWeight: 900,
                  padding: "10px 18px",
                  lineHeight: 1,
                  transform: `translateY(${letterY}px) rotate(${item.rot}deg) scale(${letterDrop})`,
                  boxShadow: "6px 8px 0px #000000",
                  border: item.border || "3px solid #000000",
                  display: "inline-block",
                }}
              >
                {item.char}
              </div>
            );
          })}
        </div>

        {/* Stamped Bottom Tag */}
        <div
          style={{
            backgroundColor: "#FF0055",
            color: "#FFFFFF",
            fontFamily: "'Courier New', monospace",
            fontWeight: "bold",
            fontSize: 18,
            padding: "4px 14px",
            transform: "rotate(-2deg)",
            boxShadow: "4px 4px 0px #000",
          }}
        >
          [ DIY DIGITAL CODE REVOLUTION ]
        </div>
      </div>
    </div>
  );
};
