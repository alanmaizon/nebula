import React, { useState, useRef, useEffect } from 'react';
import { Fingerprint, ArrowRight } from 'lucide-react';

interface LandingPageProps {
  onEnter: () => void;
}

export const LandingPage: React.FC<LandingPageProps> = ({ onEnter }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [cursor, setCursor] = useState({ x: -100, y: -100 });

  // Auto-animation for the light - always running
  useEffect(() => {
    let animationFrame: number;
    let angle = 0;

    const animate = () => {
      if (containerRef.current) {
        const rect = containerRef.current.getBoundingClientRect();
        const centerX = rect.width / 2;
        const centerY = rect.height / 2;
        const radius = 60; // Movement radius
        
        // Circular motion
        const x = centerX + Math.cos(angle) * radius;
        const y = centerY + Math.sin(angle) * radius;
        
        setCursor({ x, y });
        angle += 0.03;
        animationFrame = requestAnimationFrame(animate);
      }
    };

    animate();
    return () => cancelAnimationFrame(animationFrame);
  }, []);

  return (
    <div className="min-h-screen bg-black flex flex-col items-center justify-center relative overflow-hidden font-sans selection:bg-cyan-900 selection:text-cyan-100">
      
      {/* Background Grid - decorative */}
      <div className="absolute inset-0 bg-[linear-gradient(to_right,#111_1px,transparent_1px),linear-gradient(to_bottom,#111_1px,transparent_1px)] bg-[size:4rem_4rem] opacity-20 pointer-events-none"></div>

      <div className="relative z-10 flex flex-col items-center gap-12">
        
        {/* Animated Fingerprint Container (Non-interactive) */}
        <div 
          ref={containerRef}
          className="relative w-64 h-64"
        >
          {/* Layer 1: The dark base fingerprint (barely visible) */}
          <Fingerprint 
            className="w-full h-full text-zinc-900 absolute inset-0 transition-colors duration-700" 
            strokeWidth={1}
          />

          {/* Layer 2: The Neon Fingerprint (Masked) */}
          <div 
            className="absolute inset-0 pointer-events-none"
            style={{
              // CSS Mask to reveal this layer based on cursor position
              maskImage: `radial-gradient(circle 120px at ${cursor.x}px ${cursor.y}px, black 20%, transparent 100%)`,
              WebkitMaskImage: `radial-gradient(circle 120px at ${cursor.x}px ${cursor.y}px, black 20%, transparent 100%)`,
            }}
          >
            <Fingerprint 
              className="w-full h-full text-cyan-400 drop-shadow-[0_0_15px_rgba(34,211,238,0.8)] filter" 
              strokeWidth={1.2}
            />
          </div>

          {/* Scanner Light visual cue */}
          <div 
            className="absolute w-4 h-4 bg-cyan-400 rounded-full blur-xl pointer-events-none transition-opacity duration-300 opacity-60"
            style={{
              left: cursor.x,
              top: cursor.y,
              transform: 'translate(-50%, -50%)',
            }}
          />
        </div>

        {/* Text Content */}
        <div className="text-center space-y-6">
          <h1 className="text-6xl md:text-8xl font-bold tracking-tighter text-white">
            Siamese
            <span className="text-cyan-500 text-6xl">.</span>
          </h1>
          
          <p className="text-zinc-500 text-lg md:text-xl max-w-md mx-auto font-light tracking-wide">
            Detailed Incident Analysis <br /> powered by Gemini 
          </p>

          <button 
            onClick={onEnter}
            className="group relative inline-flex items-center gap-3 px-8 py-4 bg-zinc-900 text-zinc-100 rounded-full overflow-hidden transition-all hover:bg-zinc-800 border border-zinc-800 hover:border-cyan-900 hover:shadow-[0_0_20px_rgba(8,145,178,0.3)] mt-4"
          >
            <span className="relative font-medium tracking-widest uppercase text-sm">Enter Workspace</span>
            <ArrowRight className="w-4 h-4 text-cyan-500 group-hover:translate-x-1 transition-transform" />
          </button>
        </div>

      </div>
      
      {/* Footer hint - Made Lighter (text-zinc-300) */}
      <div className="absolute bottom-8 text-zinc-300 text-xs tracking-[0.2em] uppercase">
        Secure • Local • Private
      </div>
    </div>
  );
};