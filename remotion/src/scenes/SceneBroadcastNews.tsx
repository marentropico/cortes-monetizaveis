import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";

export const SceneBroadcastNews: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Entrance slide for the lower-third graphics
  const lowerThirdSlide = spring({
    frame,
    fps,
    config: { damping: 16, stiffness: 140, mass: 0.8 },
  });

  const bannerY = interpolate(lowerThirdSlide, [0, 1], [300, 0]);

  // Main camera slow zoom-in on the studio
  const cameraZoom = interpolate(frame, [0, 30], [1, 1.05]);

  // Scrolling ticker offset
  const tickerOffset = interpolate(frame, [0, 30], [0, -450]);

  // Flashing live red dot
  const flashOpacity = Math.sin(frame * 0.8) > 0 ? 1 : 0.2;

  // Background grid rotation/shift
  const gridShift = (frame * 3) % 60;

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        backgroundColor: "#070e1e",
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
        fontFamily: "'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
        overflow: "hidden",
        position: "relative",
        transform: `scale(${cameraZoom})`,
      }}
    >
      {/* Broadcast Digital Grid & World Map backdrop */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          backgroundImage:
            "linear-gradient(rgba(0, 132, 255, 0.12) 1px, transparent 1px), linear-gradient(90deg, rgba(0, 132, 255, 0.12) 1px, transparent 1px)",
          backgroundSize: "60px 60px",
          backgroundPosition: `0px ${gridShift}px`,
        }}
      />

      {/* Radial Blue Studio Vignette */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background:
            "radial-gradient(ellipse at center, rgba(13, 50, 110, 0.6) 0%, rgba(3, 8, 20, 0.95) 100%)",
        }}
      />

      {/* Horizontal TV Scanlines */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          backgroundImage:
            "repeating-linear-gradient(0deg, rgba(0,0,0,0.15) 0px, rgba(0,0,0,0.15) 1px, transparent 1px, transparent 3px)",
          pointerEvents: "none",
        }}
      />

      {/* Top TV Bar: Studio Info & Live Clock */}
      <div
        style={{
          position: "relative",
          zIndex: 10,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "24px 48px",
          borderBottom: "1px solid rgba(255, 255, 255, 0.1)",
          background: "linear-gradient(180deg, rgba(0,0,0,0.7) 0%, transparent 100%)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          {/* Live Badge */}
          <div
            style={{
              backgroundColor: "#d90429",
              color: "#ffffff",
              padding: "5px 14px",
              borderRadius: 4,
              fontWeight: 900,
              fontSize: 14,
              letterSpacing: "0.15em",
              display: "flex",
              alignItems: "center",
              gap: 8,
              boxShadow: "0 0 15px rgba(217, 4, 41, 0.8)",
            }}
          >
            <div
              style={{
                width: 9,
                height: 9,
                borderRadius: "50%",
                backgroundColor: "#ffffff",
                opacity: flashOpacity,
              }}
            />
            AO VIVO
          </div>
          <span style={{ color: "#ffffff", fontSize: 16, fontWeight: 700, letterSpacing: "0.1em" }}>
            REMOTION NEWS 24H
          </span>
        </div>

        <div style={{ color: "rgba(255,255,255,0.7)", fontSize: 15, fontFamily: "monospace" }}>
          ESTÚDIO CENTRAL // 15:43:00 GMT-3
        </div>
      </div>

      {/* Center Holographic Studio Headline: "OLÁ MUNDO" */}
      <div
        style={{
          position: "relative",
          zIndex: 5,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <div
          style={{
            fontSize: 20,
            letterSpacing: "0.3em",
            color: "#00d2ff",
            textTransform: "uppercase",
            fontWeight: 800,
            marginBottom: 10,
            textShadow: "0 0 12px rgba(0, 210, 255, 0.8)",
          }}
        >
          03 // PLANTÃO EXTRAORDINÁRIO
        </div>

        <div
          style={{
            fontSize: 96,
            fontWeight: 900,
            color: "#ffffff",
            letterSpacing: "-0.01em",
            textTransform: "uppercase",
            textShadow: "0 8px 30px rgba(0, 0, 0, 0.8), 0 0 40px rgba(0, 140, 255, 0.4)",
          }}
        >
          OLÁ MUNDO
        </div>
      </div>

      {/* Modern Broadcast Lower-Third Graphic Banner */}
      <div
        style={{
          position: "relative",
          zIndex: 15,
          transform: `translateY(${bannerY}px)`,
        }}
      >
        {/* Main Urgent Banner */}
        <div
          style={{
            margin: "0 48px",
            display: "flex",
            borderRadius: "8px 8px 0 0",
            overflow: "hidden",
            boxShadow: "0 -10px 40px rgba(0, 0, 0, 0.6)",
          }}
        >
          {/* Breaking Red Tag */}
          <div
            style={{
              backgroundColor: "#d90429",
              color: "#ffffff",
              padding: "16px 28px",
              fontWeight: 900,
              fontSize: 24,
              letterSpacing: "0.08em",
              display: "flex",
              alignItems: "center",
              borderRight: "4px solid #ef233c",
            }}
          >
            URGENTE
          </div>

          {/* Headline Content */}
          <div
            style={{
              flex: 1,
              backgroundColor: "rgba(10, 25, 55, 0.95)",
              backdropFilter: "blur(20px)",
              color: "#ffffff",
              padding: "16px 30px",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              borderTop: "3px solid #00b4d8",
            }}
          >
            <div style={{ fontSize: 26, fontWeight: 800, letterSpacing: "-0.01em" }}>
              PRIMEIRO VÍDEO RENDERIZADO PROGRAMATICAMENTE COM REACT
            </div>
            <div style={{ color: "#ffd166", fontWeight: 700, fontSize: 16 }}>
              ED. ESPECIAL
            </div>
          </div>
        </div>

        {/* Ticker Tape at the very bottom */}
        <div
          style={{
            backgroundColor: "#03045e",
            color: "#e0e1dd",
            padding: "10px 0",
            overflow: "hidden",
            whiteSpace: "nowrap",
            borderTop: "1px solid rgba(255, 255, 255, 0.15)",
            fontSize: 16,
            fontWeight: 600,
            display: "flex",
          }}
        >
          <div
            style={{
              display: "inline-block",
              transform: `translateX(${tickerOffset}px)`,
              letterSpacing: "0.04em",
            }}
          >
            +++ PLANTÃO AO VIVO: REMOTION TRANSFORMA CÓDIGO TYPESCRIPT EM FRAMEWORK AUDIOVISUAL DE ALTA PERFORMANCE +++ 5 ESTILOS TESTADOS EM 5 SEGUNDOS +++ CHROMIUM HEADLESS EM TEMPO REAL +++
          </div>
        </div>
      </div>
    </div>
  );
};
