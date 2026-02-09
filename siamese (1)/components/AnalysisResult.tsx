import React from 'react';
import { AnalysisState } from '../types';
import { AlertCircle, CheckCircle2, Clock, ShieldAlert, Search, FileJson, Terminal, Sparkles, Download } from 'lucide-react';

interface AnalysisResultProps {
  state: AnalysisState;
}

export const AnalysisResult: React.FC<AnalysisResultProps> = ({ state }) => {
  if (state.status === 'idle') {
    return (
      <div className="h-full flex flex-col items-center justify-center text-zinc-600 p-8 border border-dashed border-zinc-800 rounded-3xl bg-zinc-900/20 backdrop-blur-sm">
        <Search className="w-12 h-12 mb-4 opacity-20" />
        <p className="text-sm tracking-wide font-light">Waiting for input data...</p>
      </div>
    );
  }

  if (state.status === 'loading') {
    return (
      <div className="h-full flex flex-col items-center justify-center p-12">
        <div className="relative w-16 h-16 mb-6">
            <div className="absolute inset-0 rounded-full border-4 border-zinc-800"></div>
            <div className="absolute inset-0 rounded-full border-4 border-cyan-500 border-t-transparent animate-spin"></div>
            <div className="absolute inset-0 rounded-full blur-md border-4 border-cyan-400 border-t-transparent animate-spin opacity-50"></div>
        </div>
        <p className="text-cyan-400/80 font-medium animate-pulse tracking-widest text-sm uppercase">Analyzing Artifacts</p>
      </div>
    );
  }

  if (state.status === 'error') {
    return (
      <div className="bg-red-500/10 border border-red-500/20 p-6 rounded-2xl backdrop-blur-md">
        <div className="flex items-start">
          <AlertCircle className="w-6 h-6 text-red-400 mt-0.5 mr-4 flex-shrink-0" />
          <div>
            <h3 className="text-red-200 font-bold mb-1">Analysis Failed</h3>
            <p className="text-red-400/80 text-sm">{state.error}</p>
          </div>
        </div>
      </div>
    );
  }

  const { parsedReport, rawResponse } = state;

  const handleDownloadJson = () => {
    if (!rawResponse) return;
    
    // Create blob and download link
    const blob = new Blob([rawResponse], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    
    // Generate filename with timestamp
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
    link.href = url;
    link.download = `incident-analysis-${timestamp}.json`;
    
    document.body.appendChild(link);
    link.click();
    
    // Cleanup
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-6">
      {/* Parsed Report Card */}
      {parsedReport && (
        <div className="bg-zinc-900/40 backdrop-blur-xl rounded-3xl border border-white/5 shadow-2xl overflow-hidden relative">
          {/* Top light reflection effect */}
          <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-cyan-500/50 to-transparent opacity-50"></div>
          
          <div className="bg-white/5 px-6 py-4 border-b border-white/5 flex items-center justify-between">
            <h2 className="font-medium text-cyan-100 flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-cyan-400" />
              Analysis Report
            </h2>
            <div className="flex items-center gap-3">
                <span className="text-[10px] font-bold uppercase text-zinc-500 tracking-widest">Confidence</span>
                <span className={`px-3 py-1 rounded-full text-xs font-bold border ${
                    (parsedReport.confidence || 0) > 0.8 ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400 shadow-[0_0_10px_rgba(16,185,129,0.2)]' : 
                    (parsedReport.confidence || 0) > 0.5 ? 'bg-yellow-500/10 border-yellow-500/30 text-yellow-400' : 'bg-red-500/10 border-red-500/30 text-red-400'
                }`}>
                    {((parsedReport.confidence || 0) * 100).toFixed(0)}%
                </span>
            </div>
          </div>
          
          <div className="p-6 space-y-8">
            <div>
              <h3 className="text-xs font-bold text-zinc-500 uppercase tracking-widest mb-3">Summary</h3>
              <p className="text-zinc-300 leading-relaxed font-light text-lg">{parsedReport.summary || "No summary provided."}</p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
              <div className="bg-black/20 p-5 rounded-2xl border border-white/5">
                <h3 className="text-xs font-bold text-rose-400 uppercase tracking-widest mb-4 flex items-center">
                  <ShieldAlert className="w-4 h-4 mr-2" /> Root Causes
                </h3>
                <ul className="space-y-3">
                  {(parsedReport.root_causes || []).map((cause, idx) => (
                    <li key={idx} className="flex items-start text-sm text-zinc-300">
                      <span className="mr-3 text-rose-500 mt-1.5 w-1.5 h-1.5 bg-rose-500 rounded-full shadow-[0_0_8px_rgba(244,63,94,0.8)] flex-shrink-0"></span>
                      {cause}
                    </li>
                  ))}
                  {(!parsedReport.root_causes || parsedReport.root_causes.length === 0) && (
                    <li className="text-sm text-zinc-600 italic">No root causes listed.</li>
                  )}
                </ul>
              </div>

               <div className="bg-black/20 p-5 rounded-2xl border border-white/5">
                <h3 className="text-xs font-bold text-cyan-400 uppercase tracking-widest mb-4 flex items-center">
                   <Clock className="w-4 h-4 mr-2" /> Timeline
                </h3>
                <ul className="space-y-4 relative border-l border-zinc-800 ml-2 pl-4">
                  {(parsedReport.timeline || []).map((item, idx) => (
                    <li key={idx} className="text-sm text-zinc-400 relative">
                      <div className="absolute -left-[21px] top-1.5 w-2.5 h-2.5 bg-zinc-900 border border-cyan-500/50 rounded-full"></div>
                      {item}
                    </li>
                  ))}
                   {(!parsedReport.timeline || parsedReport.timeline.length === 0) && (
                    <li className="text-sm text-zinc-600 italic">No timeline provided.</li>
                  )}
                </ul>
              </div>
            </div>

            <div>
               <h3 className="text-xs font-bold text-emerald-400 uppercase tracking-widest mb-4 flex items-center">
                  <CheckCircle2 className="w-4 h-4 mr-2" /> Mitigations & Follow-ups
               </h3>
               <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                 {(parsedReport.mitigations || []).map((m, i) => (
                     <div key={`mit-${i}`} className="flex gap-3 bg-emerald-500/5 border border-emerald-500/10 p-3 rounded-xl items-start">
                         <span className="text-emerald-500 font-bold mt-0.5">✓</span>
                         <span className="text-zinc-300 text-sm">{m}</span>
                     </div>
                 ))}
                  {(parsedReport.follow_ups || []).map((f, i) => (
                     <div key={`fol-${i}`} className="flex gap-3 bg-blue-500/5 border border-blue-500/10 p-3 rounded-xl items-start">
                         <span className="text-blue-500 font-bold mt-0.5">→</span>
                         <span className="text-zinc-300 text-sm">{f}</span>
                     </div>
                 ))}
               </div>
            </div>

             <div>
                <h3 className="text-xs font-bold text-zinc-500 uppercase tracking-widest mb-3">Evidence</h3>
                <div className="bg-black/40 rounded-xl p-4 font-mono text-xs text-zinc-400 border border-white/5 overflow-x-auto">
                    {(parsedReport.evidence || []).map((e, i) => (
                        <div key={i} className="mb-2 last:mb-0 border-l-2 border-zinc-700 pl-3 py-0.5 hover:border-cyan-500/50 hover:text-cyan-100 transition-colors cursor-default">{e}</div>
                    ))}
                    {(!parsedReport.evidence || parsedReport.evidence.length === 0) && (
                        <div className="text-zinc-700 italic">No evidence items extracted.</div>
                    )}
                </div>
            </div>
          </div>
        </div>
      )}

      {/* Raw Response Card */}
      <div className="bg-zinc-900/40 backdrop-blur-xl rounded-3xl border border-white/5 shadow-lg overflow-hidden">
        <div className="bg-white/5 px-6 py-3 border-b border-white/5 flex items-center justify-between">
           <h2 className="font-medium text-zinc-400 flex items-center text-xs tracking-wider uppercase">
              <Terminal className="w-4 h-4 mr-2 text-zinc-500" />
              Raw JSON Response
            </h2>
            {rawResponse && (
              <button
                onClick={handleDownloadJson}
                className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-[10px] font-bold uppercase tracking-wider text-zinc-300 transition-colors border border-white/5 hover:border-white/10"
                title="Download JSON"
              >
                <Download className="w-3 h-3" />
                Download
              </button>
            )}
        </div>
        <div className="p-0">
            <pre className="p-6 bg-black/40 text-[10px] md:text-xs font-mono text-emerald-400/80 overflow-auto max-h-60 scrollbar-thin">
                {rawResponse || "// Waiting for analysis..."}
            </pre>
        </div>
      </div>
    </div>
  );
};
