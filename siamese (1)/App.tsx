import React, { useState } from 'react';
import { FileUpload } from './components/FileUpload';
import { AnalysisResult } from './components/AnalysisResult';
import { LandingPage } from './components/LandingPage';
import { analyzeIncident } from './services/geminiService';
import { FileArtifact, AnalysisState } from './types';
import { DEFAULT_MODEL } from './constants';
import { AlertTriangle, Fingerprint, Play, Cpu, Sparkles } from 'lucide-react';

const App: React.FC = () => {
  // State to manage view: 'landing' or 'app'
  const [showLanding, setShowLanding] = useState(true);

  const [files, setFiles] = useState<FileArtifact[]>([]);
  const [question, setQuestion] = useState('Analyze these logs and identify the root cause of the failure.');
  const [model, setModel] = useState(DEFAULT_MODEL);
  
  const [analysisState, setAnalysisState] = useState<AnalysisState>({
    status: 'idle',
    rawResponse: null,
    parsedReport: null,
    error: null,
  });

  const handleAnalyze = async () => {
    if (files.length === 0) {
      setAnalysisState(prev => ({ ...prev, error: "Please upload at least one file to analyze." }));
      return;
    }
    if (!question.trim()) {
      setAnalysisState(prev => ({ ...prev, error: "Please enter a question regarding the incident." }));
      return;
    }

    setAnalysisState({ status: 'loading', rawResponse: null, parsedReport: null, error: null });

    try {
      // Accessing API Key from process.env as per strict instructions
      const apiKey = process.env.API_KEY || ""; 
      
      const { text, json } = await analyzeIncident(apiKey, model, question, files);
      
      setAnalysisState({
        status: 'success',
        rawResponse: text,
        parsedReport: json || null,
        error: null,
      });
    } catch (err: any) {
      setAnalysisState({
        status: 'error',
        rawResponse: null,
        parsedReport: null,
        error: err.message || "An unknown error occurred",
      });
    }
  };

  // If in landing mode, return the Landing Page component
  if (showLanding) {
    return <LandingPage onEnter={() => setShowLanding(false)} />;
  }

  // Main Application Layout
  return (
    <div className="min-h-screen bg-black text-zinc-100 font-sans p-4 md:p-8 relative selection:bg-cyan-900 selection:text-cyan-100">
      
      {/* Background Grid - Fixed */}
      <div className="fixed inset-0 bg-[linear-gradient(to_right,#18181b_1px,transparent_1px),linear-gradient(to_bottom,#18181b_1px,transparent_1px)] bg-[size:4rem_4rem] opacity-20 pointer-events-none z-0"></div>

      <div className="max-w-7xl mx-auto space-y-8 relative z-10">
        
        {/* Header */}
        <header className="flex flex-col md:flex-row md:items-end justify-between pb-8 border-b border-white/5">
          <div>
            {/* Updated Tracking to 'tighter' and structure to ensure 'Siamese.' is connected */}
            <h1 className="text-4xl font-bold text-white flex items-center gap-3 tracking-tighter">
              <Fingerprint className="w-8 h-8 text-cyan-500" strokeWidth={1.5} />
              <span>Siamese<span className="text-cyan-500">.</span></span>
            </h1>
            <p className="text-zinc-500 mt-2 text-sm font-light tracking-wide uppercase">AI-Powered Incident Analysis Workspace</p>
          </div>
          <div className="mt-4 md:mt-0 flex items-center text-[10px] font-bold tracking-widest text-zinc-500 bg-zinc-900/50 px-3 py-1.5 rounded-full border border-white/5">
            <AlertTriangle className="w-3 h-3 mr-2 text-zinc-600" />
             CLIENT-SIDE • LOCAL PROCESSING
          </div>
        </header>

        {/* Main Content Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
          
          {/* Left Column: Controls & Input */}
          <div className="lg:col-span-4 space-y-6">
            
            {/* File Upload Card */}
            <div className="bg-zinc-900/40 backdrop-blur-xl p-6 rounded-3xl border border-white/5 shadow-xl">
              <h2 className="text-sm font-bold text-zinc-400 uppercase tracking-widest mb-6 flex items-center gap-2">
                 <span className="w-1.5 h-1.5 rounded-full bg-cyan-500"></span>
                 Artifacts
              </h2>
              <FileUpload files={files} onFilesChange={setFiles} />
            </div>

            {/* Config Card */}
            <div className="bg-zinc-900/40 backdrop-blur-xl p-6 rounded-3xl border border-white/5 shadow-xl space-y-6">
               <h2 className="text-sm font-bold text-zinc-400 uppercase tracking-widest flex items-center gap-2">
                 <span className="w-1.5 h-1.5 rounded-full bg-cyan-500"></span>
                 Configuration
              </h2>
               
               <div>
                 <label className="block text-xs font-medium text-zinc-500 mb-2 uppercase tracking-wide">Incident Question</label>
                 <textarea 
                    value={question}
                    onChange={(e) => setQuestion(e.target.value)}
                    className="w-full p-4 bg-black/40 border border-white/10 rounded-2xl text-sm text-zinc-200 focus:ring-1 focus:ring-cyan-500/50 focus:border-cyan-500/50 outline-none min-h-[120px] resize-y placeholder-zinc-700 transition-all"
                    placeholder="e.g., What caused the latency spike at 14:00?"
                 />
               </div>

               <div>
                 <label className="block text-xs font-medium text-zinc-500 mb-2 uppercase tracking-wide flex items-center gap-2">
                    Model
                 </label>
                 <div className="relative">
                    <Cpu className="absolute left-3 top-3 w-4 h-4 text-zinc-600" />
                    <input 
                        type="text"
                        value={model}
                        onChange={(e) => setModel(e.target.value)}
                        className="w-full pl-10 pr-4 py-3 bg-black/40 border border-white/10 rounded-xl text-xs font-mono text-zinc-300 focus:ring-1 focus:ring-cyan-500/50 focus:border-cyan-500/50 outline-none transition-all"
                        placeholder="gemini-3-flash-preview"
                    />
                 </div>
                 <p className="text-[10px] text-zinc-600 mt-2 text-right font-mono">default: {DEFAULT_MODEL}</p>
               </div>

               <button
                  onClick={handleAnalyze}
                  disabled={analysisState.status === 'loading'}
                  className="group w-full relative overflow-hidden bg-zinc-100 hover:bg-white text-black font-bold py-4 px-4 rounded-full transition-all shadow-[0_0_20px_rgba(255,255,255,0.1)] hover:shadow-[0_0_25px_rgba(6,182,212,0.4)] disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2 mt-4"
                >
                   {/* Button glow gradient */}
                  <div className="absolute inset-0 bg-gradient-to-r from-transparent via-cyan-400/20 to-transparent -translate-x-[100%] group-hover:translate-x-[100%] transition-transform duration-700 pointer-events-none"></div>
                  
                  {analysisState.status === 'loading' ? (
                      <span className="text-xs uppercase tracking-widest">Processing...</span>
                  ) : (
                      <>
                        <Sparkles className="w-4 h-4 text-cyan-600" />
                        <span className="text-xs uppercase tracking-widest">Start Analysis</span>
                      </>
                  )}
                </button>
            </div>
          </div>

          {/* Right Column: Output */}
          <div className="lg:col-span-8">
             <AnalysisResult state={analysisState} />
          </div>

        </div>
      </div>
    </div>
  );
};

export default App;