import React, { useState, useRef, useEffect } from 'react';
import { Check, Video, User, Radio, Trash2, FileText, Tv, Image, Layers, Film } from 'lucide-react';
import io from 'socket.io-client';

const styles = {
  container: {
    display: 'flex',
    height: '100vh',
    backgroundColor: 'white',
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
  },
  sidebar: {
    width: '256px',
    borderRight: '1px solid #e5e7eb',
    display: 'flex',
    flexDirection: 'column',
  },
  sidebarHeader: {
    padding: '16px',
    borderBottom: '1px solid #e5e7eb',
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
  },
  sidebarTitle: {
    fontWeight: 600,
    color: '#111827',
  },
  sidebarContent: {
    flex: 1,
    overflowY: 'auto',
  },
  sectionHeader: {
    padding: '8px 16px',
    fontSize: '12px',
    fontWeight: 600,
    color: '#6b7280',
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
  },
  stageButton: {
    width: '100%',
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
    padding: '10px 16px',
    textAlign: 'left',
    border: 'none',
    background: 'none',
    cursor: 'pointer',
    transition: 'background-color 0.2s',
    position: 'relative',
  },
  stageButtonHover: {
    backgroundColor: '#f9fafb',
  },
  stageButtonSelected: {
    backgroundColor: '#f3f4f6',
  },
  stageButtonDisabled: {
    opacity: 0.6,
    cursor: 'not-allowed',
  },
  stageName: {
    fontSize: '14px',
    fontWeight: 500,
    color: '#374151',
    flex: 1,
  },
  checkmark: {
    width: '20px',
    height: '20px',
    borderRadius: '50%',
    backgroundColor: '#10b981',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
  },
  progressBar: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    right: 0,
    height: '4px',
    backgroundColor: '#e5e7eb',
  },
  progressFill: {
    height: '100%',
    backgroundColor: '#3b82f6',
    transition: 'width 0.3s',
  },
  mainContent: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
  },
  emptyState: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    color: '#9ca3af',
  },
  emptyStateTitle: {
    fontSize: '20px',
    fontWeight: 500,
    marginBottom: '8px',
  },
  emptyStateText: {
    fontSize: '14px',
  },
  contentArea: {
    flex: 1,
    padding: '24px',
  },
  contentInner: {
    height: '100%',
    display: 'flex',
    flexDirection: 'column',
  },
  logHeader: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: '16px',
  },
  logTitle: {
    fontSize: '18px',
    fontWeight: 600,
    color: '#111827',
  },
  clearButton: {
    padding: '6px 12px',
    fontSize: '14px',
    color: '#4b5563',
    backgroundColor: 'transparent',
    border: 'none',
    borderRadius: '4px',
    cursor: 'pointer',
    transition: 'all 0.2s',
  },
  terminal: {
    flex: 1,
    backgroundColor: '#1f2937',
    borderRadius: '8px',
    overflow: 'hidden',
    display: 'flex',
    flexDirection: 'column',
  },
  terminalContent: {
    flex: 1,
    padding: '16px',
    overflowY: 'auto',
    fontFamily: 'monospace',
    fontSize: '14px',
  },
  terminalLine: {
    marginBottom: '4px',
  },
  terminalInput: {
    borderTop: '1px solid #374151',
    padding: '12px',
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
  },
  terminalPrompt: {
    color: '#10b981',
    fontFamily: 'monospace',
    fontSize: '14px',
  },
  terminalInputField: {
    flex: 1,
    backgroundColor: 'transparent',
    color: '#f3f4f6',
    fontFamily: 'monospace',
    fontSize: '14px',
    border: 'none',
    outline: 'none',
  },
};

const YoutubePipeline = () => {
  const [selectedStage, setSelectedStage] = useState(null);
  const [logs, setLogs] = useState([]);
  const [executionStates, setExecutionStates] = useState({});
  const [currentInput, setCurrentInput] = useState('');
  const [waitingForInput, setWaitingForInput] = useState(null);
  const [socket, setSocket] = useState(null);
  const [isAutoRunning, setIsAutoRunning] = useState(false);
  const [hoveredStage, setHoveredStage] = useState(null);
  const terminalRef = useRef(null);

  const mainStages = [
    { id: 'create-profile', name: 'Create Profile', icon: User, file: 'profile_generator.py' },
    { id: 'channel-info', name: 'Channel Info', icon: Radio, file: 'channel_info.py' },
    { id: 'clean-base', name: 'Clean Base', icon: Trash2, file: 'clean_bases.py' }
  ];

  const pipelineStages = [
    { id: 'get-scripts', name: 'Get Scripts', icon: FileText, file: 'get_scripts.py' },
    { id: 'srt-generator', name: 'SRT Generator', icon: Tv, file: 'srt_generator.py' },
    { id: 'image-suggestions', name: 'Image Suggestions', icon: Image, file: 'suggestion_generator.py' },
    { id: 'image-generator', name: 'Image Generator', icon: Layers, file: 'image_generator.py' },
    { id: 'image-render', name: 'Image Render', icon: Film, file: 'make_and_render.py' }
  ];

  useEffect(() => {
    const newSocket = io('http://localhost:5000');
    
    newSocket.on('connected', (data) => {
      addLog('Connected to backend', 'system');
    });

    newSocket.on('script_output', (data) => {
      addLog(data.output, data.type);
      updateProgress(data.stage_id, 'running');
    });

    newSocket.on('request_input', (data) => {
      addLog(data.prompt, 'input');
      setWaitingForInput(data.stage_id);
    });

    newSocket.on('execution_started', (data) => {
      addLog(`Starting execution of ${data.stage_id}...`, 'system');
      setExecutionStates(prev => ({
        ...prev,
        [data.stage_id]: { progress: 0, status: 'running' }
      }));
    });

    newSocket.on('execution_complete', (data) => {
      const status = data.status === 'success' 
        ? 'completed' 
        : data.status === 'stopped'
          ? 'stopped'
          : 'error';
      setExecutionStates(prev => ({
        ...prev,
        [data.stage_id]: { progress: 100, status }
      }));
      addLog(
        `Execution ${data.status === 'success' ? 'completed successfully' : 'failed'}!`,
        data.status === 'success' ? 'success' : 'error'
      );
    });

    newSocket.on('execution_error', (data) => {
      addLog(`Error: ${data.error}`, 'error');
      setExecutionStates(prev => ({
        ...prev,
        [data.stage_id]: { progress: 0, status: 'error' }
      }));
    });

    newSocket.on('input_sent', (data) => {
      addLog(`> ${data.input}`, 'user');
    });

    setSocket(newSocket);

    return () => {
      newSocket.close();
    };
  }, []);

  useEffect(() => {
    if (terminalRef.current) {
      terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
    }
  }, [logs]);

  const addLog = (message, type = 'info') => {
    setLogs(prev => [...prev, { message, type, timestamp: new Date() }]);
  };

  const updateProgress = (stageId, status) => {
    setExecutionStates(prev => {
      const current = prev[stageId] || { progress: 0, status: 'idle' };
      const newProgress = Math.min(current.progress + 5, 95);
      return {
        ...prev,
        [stageId]: { progress: newProgress, status }
      };
    });
  };

  const executeStageAndWait = (stage) => {
    return new Promise((resolve) => {
      if (!socket) {
        addLog('Not connected to backend', 'error');
        resolve({ stage_id: stage.id, status: 'error' });
        return;
      }

      const handleComplete = (data) => {
        if (data.stage_id !== stage.id) return;
        socket.off('execution_complete', handleComplete);
        resolve(data);
      };

      socket.on('execution_complete', handleComplete);
      executeStage(stage);
    });
  };

  const startFullPipeline = async () => {
    if (!socket) {
      addLog('Not connected to backend', 'error');
      return;
    }
    if (isAutoRunning) return;

    setIsAutoRunning(true);
    addLog('Starting full pipeline...', 'system');

    for (const stage of [...pipelineStages]) {
      setSelectedStage(stage.id);
      const result = await executeStageAndWait(stage);
      if (result.status !== 'success') {
        addLog(`Pipeline halted at ${stage.name}`, 'error');
        setIsAutoRunning(false);
        return;
      }
    }

    addLog('Pipeline completed successfully!', 'success');
    setIsAutoRunning(false);
  };

  const shutdownAll = () => {
    if (!socket) return;
    const runningIds = Object.entries(executionStates)
      .filter(([, state]) => state?.status === 'running')
      .map(([id]) => id);

    if (runningIds.length === 0) {
      addLog('No running stages to stop.', 'system');
      return;
    }

    runningIds.forEach((id) => socket.emit('stop_stage', { stage_id: id }));
    addLog(`Shutdown requested for ${runningIds.length} stage(s).`, 'system');
    setWaitingForInput(null);
    setIsAutoRunning(false);
    setExecutionStates((prev) => {
      const next = { ...prev };
      runningIds.forEach((id) => {
        next[id] = { progress: 0, status: 'stopped' };
      });
      return next;
    });
  };

  const executeStage = (stage) => {
    if (!socket) {
      addLog('Not connected to backend', 'error');
      return;
    }

    setSelectedStage(stage.id);
    socket.emit('execute_stage', {
      stage_id: stage.id,
      script_file: stage.file
    });
  };

  const handleInputSubmit = (e) => {
    e.preventDefault();
    if (currentInput.trim() && socket && waitingForInput) {
      socket.emit('send_input', {
        stage_id: waitingForInput,
        input: currentInput.trim()
      });
      setCurrentInput('');
      setWaitingForInput(null);
    }
  };

  const clearLogs = () => {
    setLogs([]);
    setExecutionStates({});
  };

  const stopExecution = () => {
    if (!socket || !selectedStage) return;
    socket.emit('stop_stage', { stage_id: selectedStage });
    addLog('Stop requested...', 'system');
    setLogs([]);
    setWaitingForInput(null);
    setExecutionStates(prev => ({
      ...prev,
      [selectedStage]: { progress: 0, status: 'stopped' }
    }));
  };

  const getLogColor = (type) => {
    switch(type) {
      case 'error': return '#f87171';
      case 'success': return '#34d399';
      case 'system': return '#60a5fa';
      case 'input': return '#fbbf24';
      case 'user': return '#22d3ee';
      default: return '#d1d5db';
    }
  };

  const StageItem = ({ stage }) => {
    const Icon = stage.icon;
    const state = executionStates[stage.id];
    const isCompleted = state?.status === 'completed';
    const isRunning = state?.status === 'running';
    const hasError = state?.status === 'error';
    const isHovered = hoveredStage === stage.id;
    const isSelected = selectedStage === stage.id;

    const buttonStyle = {
      ...styles.stageButton,
      ...(isHovered && !isRunning ? styles.stageButtonHover : {}),
      ...(isSelected ? styles.stageButtonSelected : {}),
      ...(isRunning ? styles.stageButtonDisabled : {}),
    };

    return (
      <div style={{ position: 'relative' }}>
        <button
          onClick={() => executeStage(stage)}
          disabled={isRunning}
          style={buttonStyle}
          onMouseEnter={() => setHoveredStage(stage.id)}
          onMouseLeave={() => setHoveredStage(null)}
        >
          <Icon size={18} color={hasError ? '#ef4444' : '#4b5563'} />
          <span style={{
            ...styles.stageName,
            color: hasError ? '#dc2626' : '#374151'
          }}>
            {stage.name}
          </span>
          {isCompleted && (
            <div style={styles.checkmark}>
              <Check size={14} color="white" />
            </div>
          )}
        </button>
        
        {state && state.progress > 0 && state.status === 'running' && (
          <div style={styles.progressBar}>
            <div style={{
              ...styles.progressFill,
              width: `${state.progress}%`
            }} />
          </div>
        )}
      </div>
    );
  };

  const anyRunning = Object.values(executionStates).some(
    (state) => state?.status === 'running'
  );

  return (
    <div style={styles.container}>
      <div style={styles.sidebar}>
        <div style={styles.sidebarHeader}>
          <Video size={20} color="#374151" />
          <h1 style={styles.sidebarTitle}>YouTube Pipeline</h1>
        </div>

        <div style={styles.sidebarContent}>
          <div style={{ paddingTop: '12px', paddingBottom: '12px' }}>
            <div style={styles.sectionHeader}>Main Stages</div>
            {mainStages.map(stage => (
              <StageItem key={stage.id} stage={stage} />
            ))}
          </div>

          <div style={{ 
            paddingTop: '12px', 
            paddingBottom: '12px',
            borderTop: '1px solid #e5e7eb'
          }}>
            <div style={styles.sectionHeader}>Pipeline Stages</div>
            {pipelineStages.map(stage => (
              <StageItem key={stage.id} stage={stage} />
            ))}
          </div>
        </div>
      </div>

      <div style={styles.mainContent}>
        {!selectedStage ? (
          <div style={styles.emptyState}>
            <Video size={64} color="#d1d5db" style={{ marginBottom: '16px' }} />
            <h2 style={styles.emptyStateTitle}>Content Production Pipeline</h2>
            <p style={styles.emptyStateText}>Select a pipeline stage from the sidebar to configure and execute.</p>
          </div>
        ) : (
          <div style={styles.contentArea}>
            <div style={styles.contentInner}>
            <div style={styles.logHeader}>
              <h2 style={styles.logTitle}>Execution Log</h2>
              <div style={{ display: 'flex', gap: '8px' }}>
                <button
                  onClick={startFullPipeline}
                  style={{ ...styles.clearButton, color: '#059669' }}
                  disabled={!socket || isAutoRunning || anyRunning}
                  onMouseEnter={(e) => {
                    e.target.style.color = '#047857';
                    e.target.style.backgroundColor = '#ecfdf3';
                  }}
                  onMouseLeave={(e) => {
                    e.target.style.color = '#059669';
                    e.target.style.backgroundColor = 'transparent';
                  }}
                >
                  Start All
                </button>
                <button
                  onClick={shutdownAll}
                  style={{ ...styles.clearButton, color: '#f97316' }}
                  disabled={!anyRunning}
                  onMouseEnter={(e) => {
                    e.target.style.color = '#c2410c';
                    e.target.style.backgroundColor = '#fff7ed';
                  }}
                  onMouseLeave={(e) => {
                    e.target.style.color = '#f97316';
                    e.target.style.backgroundColor = 'transparent';
                  }}
                >
                  Shutdown All
                </button>
                <button
                  onClick={stopExecution}
                  style={{ ...styles.clearButton, color: '#ef4444' }}
                  onMouseEnter={(e) => {
                    e.target.style.color = '#b91c1c';
                    e.target.style.backgroundColor = '#fee2e2';
                  }}
                  onMouseLeave={(e) => {
                    e.target.style.color = '#ef4444';
                    e.target.style.backgroundColor = 'transparent';
                  }}
                  disabled={!selectedStage || executionStates[selectedStage]?.status !== 'running'}
                >
                  Stop
                </button>
                <button
                  onClick={clearLogs}
                  style={styles.clearButton}
                  onMouseEnter={(e) => {
                    e.target.style.color = '#111827';
                    e.target.style.backgroundColor = '#f3f4f6';
                  }}
                  onMouseLeave={(e) => {
                    e.target.style.color = '#4b5563';
                    e.target.style.backgroundColor = 'transparent';
                  }}
                >
                  Clear
                </button>
              </div>
            </div>
              
              <div style={styles.terminal}>
                <div ref={terminalRef} style={styles.terminalContent}>
                  {logs.length === 0 && (
                    <div style={{ color: '#6b7280' }}>No logs yet...</div>
                  )}
                  {logs.map((log, index) => (
                    <div key={index} style={{
                      ...styles.terminalLine,
                      color: getLogColor(log.type)
                    }}>
                      {log.message}
                    </div>
                  ))}
                  {waitingForInput && (
                    <div style={{ color: '#fbbf24', animation: 'pulse 2s infinite' }}>
                      Waiting for input...
                    </div>
                  )}
                </div>

                {waitingForInput && (
                  <form onSubmit={handleInputSubmit} style={styles.terminalInput}>
                    <span style={styles.terminalPrompt}>$</span>
                    <input
                      type="text"
                      value={currentInput}
                      onChange={(e) => setCurrentInput(e.target.value)}
                      style={styles.terminalInputField}
                      placeholder="Type your input and press Enter..."
                      autoFocus
                    />
                  </form>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default YoutubePipeline;
