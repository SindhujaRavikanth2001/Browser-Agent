import { useState, useEffect, useRef } from 'react';
import { Panel, PanelGroup, PanelResizeHandle } from 'react-resizable-panels';
import {
  Box,
  Typography,
  TextField,
  Button,
  Paper,
  Toolbar,
  Tabs,
  Tab,
  Avatar,
  useTheme,
  IconButton,
  Tooltip,
  Alert,
  Snackbar
} from '@mui/material';
import { alpha } from '@mui/material/styles';
import SendIcon from '@mui/icons-material/Send';
import OpenInFullIcon from '@mui/icons-material/OpenInFull';
import CloseIcon from '@mui/icons-material/Close';
import MicIcon from '@mui/icons-material/Mic';
import MicOffIcon from '@mui/icons-material/MicOff';
import CheckIcon from '@mui/icons-material/Check';
import ClearIcon from '@mui/icons-material/Clear';
import './App.css';

// TypeScript declarations for Speech Recognition API
interface SpeechRecognitionEvent extends Event {
  resultIndex: number;
  results: SpeechRecognitionResultList;
}

interface SpeechRecognitionErrorEvent extends Event {
  error: 'network' | 'not-allowed' | 'no-speech' | 'aborted' | 'audio-capture' | 'service-not-allowed';
  message: string;
}

interface SpeechRecognitionResultList {
  readonly length: number;
  item(index: number): SpeechRecognitionResult;
  [index: number]: SpeechRecognitionResult;
}

interface SpeechRecognitionResult {
  readonly length: number;
  item(index: number): SpeechRecognitionAlternative;
  [index: number]: SpeechRecognitionAlternative;
  isFinal: boolean;
}

interface SpeechRecognitionAlternative {
  transcript: string;
  confidence: number;
}

interface SpeechRecognition extends EventTarget {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  maxAlternatives: number;
  serviceURI: string;
  grammars: any;
  
  start(): void;
  stop(): void;
  abort(): void;
  
  onstart: ((this: SpeechRecognition, ev: Event) => any) | null;
  onresult: ((this: SpeechRecognition, ev: SpeechRecognitionEvent) => any) | null;
  onerror: ((this: SpeechRecognition, ev: SpeechRecognitionErrorEvent) => any) | null;
  onend: ((this: SpeechRecognition, ev: Event) => any) | null;
  onspeechstart: ((this: SpeechRecognition, ev: Event) => any) | null;
  onspeechend: ((this: SpeechRecognition, ev: Event) => any) | null;
  onsoundstart: ((this: SpeechRecognition, ev: Event) => any) | null;
  onsoundend: ((this: SpeechRecognition, ev: Event) => any) | null;
  onaudiostart: ((this: SpeechRecognition, ev: Event) => any) | null;
  onaudioend: ((this: SpeechRecognition, ev: Event) => any) | null;
  onnomatch: ((this: SpeechRecognition, ev: SpeechRecognitionEvent) => any) | null;
}

interface SpeechRecognitionStatic {
  new(): SpeechRecognition;
}

declare global {
  interface Window {
    SpeechRecognition: SpeechRecognitionStatic;
    webkitSpeechRecognition: SpeechRecognitionStatic;
  }
}

// Define types for our application
type ChatMessage = {
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
};

type AgentAction = {
  action: string;
  details: string;
  timestamp: number;
};

function App() {
  const theme = useTheme();
  const [socket, setSocket] = useState<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [agentActions, setAgentActions] = useState<AgentAction[]>([]);
  const [browserState, setBrowserState] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [activeTab, setActiveTab] = useState(0);
  const [streamingMessage, setStreamingMessage] = useState<string>('');
  const [isStreaming, setIsStreaming] = useState(false);

  // Voice-to-text state
  const [isListening, setIsListening] = useState(false);
  const [speechSupported, setSpeechSupported] = useState(false);
  const [voiceInput, setVoiceInput] = useState('');
  const [showVoiceReview, setShowVoiceReview] = useState(false);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const [isInitializing, setIsInitializing] = useState(false);
  const recognitionRef = useRef<any>(null);
  const isListeningRef = useRef(false);
  const voiceInputRef = useRef('');

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const actionsEndRef = useRef<HTMLDivElement>(null);
  const browserEndRef = useRef<HTMLDivElement>(null);

  // Update voiceInputRef whenever voiceInput changes
  useEffect(() => {
    voiceInputRef.current = voiceInput;
  }, [voiceInput]);

  // Initialize Speech Recognition
  useEffect(() => {
    // Check if Speech Recognition is supported
    const SpeechRecognitionClass = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    
    if (SpeechRecognitionClass) {
      setSpeechSupported(true);
      console.log('Speech Recognition is supported');
      
      // Pre-request microphone permission on component mount
      if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
        navigator.mediaDevices.getUserMedia({ audio: true })
          .then(() => {
            console.log('Microphone permission pre-granted');
          })
          .catch((error) => {
            console.log('Microphone permission not granted yet:', error);
          });
      }
    } else {
      console.warn('Speech Recognition not supported in this browser');
      setSpeechSupported(false);
    }
  }, []);

  // Create recognition instance when needed
  const createRecognition = () => {
    const SpeechRecognitionClass = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    
    if (!SpeechRecognitionClass) return null;
    
    const recognition = new SpeechRecognitionClass() as SpeechRecognition;
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = 'en-US';

    recognition.onstart = () => {
      console.log('Speech recognition started');
      setIsListening(true);
      setIsInitializing(false);
      setVoiceError(null);
      isListeningRef.current = true;
    };

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      let finalTranscript = '';
      
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        if (result.isFinal) {
          finalTranscript += result[0].transcript;
        }
      }
      
      if (finalTranscript) {
        console.log('Final transcript:', finalTranscript);
        const newVoiceInput = voiceInputRef.current + finalTranscript + ' ';
        setVoiceInput(newVoiceInput);
        voiceInputRef.current = newVoiceInput;
      }
    };

    recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
      console.error('Speech recognition error:', event.error);
      setIsListening(false);
      setIsInitializing(false);
      isListeningRef.current = false;
      
      switch (event.error) {
        case 'network':
          setVoiceError('Network error. Please check your internet connection.');
          break;
        case 'not-allowed':
          setVoiceError('Microphone access denied. Please allow microphone access and try again.');
          break;
        case 'no-speech':
          setVoiceError('No speech detected. Please try speaking again.');
          break;
        case 'audio-capture':
          setVoiceError('Microphone not found. Please check your microphone.');
          break;
        case 'service-not-allowed':
          setVoiceError('Speech recognition service not allowed. Please check browser settings.');
          break;
        case 'aborted':
          console.log('Speech recognition was aborted');
          break;
        default:
          setVoiceError(`Speech recognition error: ${event.error}. Please try again.`);
      }
    };

    recognition.onend = () => {
      console.log('Speech recognition ended');
      setIsListening(false);
      setIsInitializing(false);
      isListeningRef.current = false;
      
      // Use a small delay to ensure state updates are complete
      setTimeout(() => {
        const currentVoiceInput = voiceInputRef.current;
        console.log('Checking voice input on end:', currentVoiceInput);
        
        if (currentVoiceInput && currentVoiceInput.trim()) {
          console.log('Showing voice review panel');
          setShowVoiceReview(true);
        } else {
          console.log('No voice input to review');
        }
      }, 100);
    };

    return recognition;
  };

  // Start voice recognition
  const startListening = async () => {
    if (isListening || isInitializing) {
      console.log('Already listening or initializing');
      return;
    }
    
    console.log('Starting voice recognition...');
    setVoiceInput('');
    voiceInputRef.current = '';
    setVoiceError(null);
    setShowVoiceReview(false);
    setIsInitializing(true);
    
    // Clean up any existing recognition
    if (recognitionRef.current) {
      try {
        recognitionRef.current.abort();
      } catch (e) {
        console.log('Error aborting previous recognition:', e);
      }
      recognitionRef.current = null;
    }
    
    try {
      const recognition = createRecognition();
      if (!recognition) {
        setVoiceError('Speech recognition not available');
        setIsInitializing(false);
        return;
      }
      
      recognitionRef.current = recognition;
      
      // Check microphone permission
      if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
        try {
          await navigator.mediaDevices.getUserMedia({ audio: true });
          console.log('Microphone permission granted, starting recognition immediately');
          recognition.start();
        } catch (error) {
          console.error('Microphone permission denied:', error);
          setVoiceError('Microphone access is required for voice input. Please allow microphone access.');
          setIsInitializing(false);
        }
      } else {
        console.log('Using fallback, starting recognition immediately');
        recognition.start();
      }
    } catch (error) {
      console.error('Error in startListening:', error);
      setVoiceError('Failed to start speech recognition. Please try again.');
      setIsInitializing(false);
    }
  };

  // Stop voice recognition
  const stopListening = () => {
    if (!isListeningRef.current && !isInitializing) return;
    
    setIsInitializing(false);
    
    if (recognitionRef.current) {
      try {
        recognitionRef.current.stop();
      } catch (error) {
        console.log('Error stopping recognition:', error);
      }
    }
  };

  // Accept voice input and put it in the text field
  const acceptVoiceInput = () => {
    setInput(voiceInput);
    setShowVoiceReview(false);
    setVoiceInput('');
    voiceInputRef.current = '';
  };

  // Reject voice input
  const rejectVoiceInput = () => {
    setShowVoiceReview(false);
    setVoiceInput('');
    voiceInputRef.current = '';
  };

  // Clear voice error
  const clearVoiceError = () => {
    setVoiceError(null);
  };

  // Connect to WebSocket server when component mounts
  useEffect(() => {
    const socketUrl = 'ws://localhost:8000/ws';
    console.log('Connecting to WebSocket at:', socketUrl);

    const newSocket = new WebSocket(socketUrl);

    newSocket.onopen = () => {
      console.log('WebSocket connection established');
      setConnected(true);
    };

    newSocket.onclose = () => {
      console.log('WebSocket connection closed');
      setConnected(false);
    };

    newSocket.onerror = (error) => {
      console.error('WebSocket error:', error);
      setConnected(false);
    };

    newSocket.onmessage = (event) => {
      const data = JSON.parse(event.data);
      console.log('Received message:', data);

      if (data.type === 'connect') {
        console.log('Connection confirmed by server');
      } else if (data.type === 'agent_message') {
        setMessages(prev => [...prev, {
          role: 'assistant',
          content: data.content,
          timestamp: Date.now()
        }]);
        setIsLoading(false);
        setActiveTab(0);
      } else if (data.type === 'agent_message_stream_start') {
        setIsStreaming(true);
        setStreamingMessage('');
        setMessages(prev => [...prev, {
          role: 'assistant',
          content: '',
          timestamp: Date.now()
        }]);
        setActiveTab(0);
      } else if (data.type === 'agent_message_stream_chunk') {
        setStreamingMessage(prev => prev + data.content);
        setMessages(prev => {
          const newMessages = [...prev];
          if (newMessages.length > 0) {
            newMessages[newMessages.length - 1] = {
              ...newMessages[newMessages.length - 1],
              content: newMessages[newMessages.length - 1].content + data.content
            };
          }
          return newMessages;
        });
      } else if (data.type === 'agent_message_stream_end') {
        setIsStreaming(false);
        setIsLoading(false);
      } else if (data.type === 'agent_action') {
        setAgentActions(prev => [...prev, {
          action: data.action,
          details: data.details,
          timestamp: Date.now()
        }]);
      } else if (data.type === 'browser_state') {
        console.log('Received browser state with image data length:',
          data.base64_image ? data.base64_image.length : 0);

        if (data.base64_image && data.base64_image.length > 0) {
          setBrowserState(data.base64_image);
        } else {
          console.warn('Received empty browser screenshot');
        }
      }
    };

    setSocket(newSocket);

    return () => {
      newSocket.close();
    };
  }, []);

  // Auto-scroll chat and action logs to bottom when new content arrives
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    actionsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [agentActions]);

  // Handle sending messages
  const sendMessage = () => {
    if (!input.trim()) return;

    const newMessage: ChatMessage = {
      role: 'user',
      content: input,
      timestamp: Date.now()
    };

    setMessages(prev => [...prev, newMessage]);

    if (socket && socket.readyState === WebSocket.OPEN) {
      console.log('Sending message via WebSocket:', input);
      socket.send(JSON.stringify({ content: input }));
    } else {
      console.log('Sending message via HTTP API:', input);
      fetch('/api/message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: input })
      })
        .then(response => response.json())
        .then(data => {
          console.log('API response:', data);
          if (data && data.response) {
            setMessages(prev => [
              ...prev,
              {
                role: 'assistant',
                content: data.response,
                timestamp: Date.now()
              }
            ]);
          }
          if (data.base64_image) {
            setBrowserState(data.base64_image);
          }
          setIsLoading(false);
        })
        .catch(error => {
          console.error('Error sending message:', error);
          setIsLoading(false);
        });
    }

    setInput('');
    setIsLoading(true);
  };

  const handleTabChange = (_: React.SyntheticEvent, newValue: number) => {
    setActiveTab(newValue);
  };

  return (
    <Box
      sx={{
        height: '100vh',
        display: 'flex',
        flexDirection: 'column',
        background: `linear-gradient(135deg, ${alpha(theme.palette.background.default, 0.7)} 0%, ${alpha(theme.palette.background.default, 0.9)} 100%)`,
        p: 1.5,
        gap: 1,
        overflow: 'hidden'
      }}
    >
      {/* Header Bubble */}
      <Paper
        elevation={0}
        className="glass-effect"
        sx={{
          borderRadius: 2,
          overflow: 'hidden',
          mb: 1,
          flexShrink: 0
        }}
      >
        <Toolbar sx={{ px: 3, minHeight: '56px' }}>
          <Avatar
            src="https://avatars.githubusercontent.com/u/114557877?s=280&v=4"
            alt="Fireworks"
            sx={{ width: 32, height: 32, mr: 1.5 }}
          />
          <Typography variant="h6" fontWeight="600">Browser AI Agent</Typography>
          <Box sx={{
            ml: 2,
            px: 1.5,
            py: 0.5,
            borderRadius: 10,
            backgroundColor: connected ? 'rgba(46, 196, 72, 0.15)' : 'rgba(239, 68, 68, 0.15)',
            border: connected ? '1px solid rgba(46, 196, 72, 0.4)' : '1px solid rgba(239, 68, 68, 0.4)'
          }}>
            <Typography
              variant="caption"
              color={connected ? theme.palette.success.main : theme.palette.error.main}
              fontWeight="600"
            >
              {connected ? 'Connected' : 'Disconnected'}
            </Typography>
          </Box>
        </Toolbar>
      </Paper>

      {/* Voice Error Snackbar */}
      <Snackbar
        open={!!voiceError}
        autoHideDuration={6000}
        onClose={clearVoiceError}
        anchorOrigin={{ vertical: 'top', horizontal: 'center' }}
      >
        <Alert onClose={clearVoiceError} severity="error" sx={{ width: '100%' }}>
          {voiceError}
        </Alert>
      </Snackbar>

      {/* Main Content Area */}
      <Box sx={{ flexGrow: 1, overflow: 'hidden', display: 'flex', gap: 0 }}>
        <PanelGroup direction="horizontal" autoSaveId="panel-group-settings">
          {/* Left Panel - Chat Interface and Agent Activity */}
          <Panel defaultSize={40} minSize={30}>
            <Paper
              elevation={0}
              className="glass-effect"
              sx={{
                height: '100%',
                borderRadius: 2,
                overflow: 'hidden',
                display: 'flex',
                flexDirection: 'column',
                mr: 0.25
              }}
            >
              {/* Tabs */}
              <Box sx={{
                borderBottom: 1,
                borderColor: 'divider',
                backgroundColor: alpha(theme.palette.background.paper, 0.6),
                flexShrink: 0
              }}>
                <Tabs
                  value={activeTab}
                  onChange={handleTabChange}
                  variant="fullWidth"
                  sx={{
                    '& .MuiTab-root': {
                      textTransform: 'none',
                      fontWeight: 500,
                      fontSize: '0.9rem'
                    },
                    '& .Mui-selected': {
                      color: theme.palette.primary.main
                    },
                    '& .MuiTabs-indicator': {
                      backgroundColor: theme.palette.primary.main
                    }
                  }}
                >
                  <Tab label="Chat" />
                  <Tab label="Agent Activity" />
                </Tabs>
              </Box>

              {/* Chat Interface */}
              <Box
                sx={{
                  display: activeTab === 0 ? 'flex' : 'none',
                  flexDirection: 'column',
                  flexGrow: 1
                }}
              >
                {/* Messages container */}
                <Box
                  sx={{
                    flexGrow: 1,
                    overflow: 'auto',
                    p: 2,
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 2,
                    backgroundColor: alpha(theme.palette.background.default, 0.3),
                    height: 0,
                    minHeight: 0
                  }}
                  className="bubble-container"
                >
                  {messages.map((msg, index) => (
                    <Box
                      key={index}
                      sx={{
                        alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start',
                        maxWidth: '90%'
                      }}
                      className="fade-in"
                    >
                      <Paper
                        elevation={0}
                        className={msg.role === 'user' ? 'bubble bubble-user' : 'bubble bubble-assistant'}
                        sx={{
                          p: 2,
                          boxShadow: msg.role === 'user'
                            ? '0 2px 8px rgba(10, 132, 255, 0.25)'
                            : '0 2px 8px rgba(0, 0, 0, 0.15)',
                        }}
                      >
                        <Typography variant="body1" whiteSpace="pre-wrap">
                          {msg.content}
                        </Typography>
                      </Paper>
                    </Box>
                  ))}
                  {isLoading && (
                    <Box sx={{ alignSelf: 'flex-start', maxWidth: '90%' }} className="fade-in">
                      <Paper
                        elevation={0}
                        className="bubble bubble-assistant"
                        sx={{
                          p: 2,
                          boxShadow: '0 2px 8px rgba(0, 0, 0, 0.15)',
                        }}
                      >
                        <Typography variant="body1">Thinking...</Typography>
                      </Paper>
                    </Box>
                  )}
                  <div ref={messagesEndRef} />
                </Box>

                {/* Input area */}
                <Box sx={{
                  p: 2,
                  backgroundColor: alpha(theme.palette.background.paper, 0.3),
                  backdropFilter: 'blur(10px)',
                  flexShrink: 0
                }}>
                  {/* Voice status indicator */}
                  {(isListening || isInitializing) && (
                    <Box sx={{ 
                      mb: 1, 
                      p: 1.5, 
                      backgroundColor: alpha(theme.palette.primary.main, 0.1),
                      borderRadius: 2,
                      border: `1px solid ${alpha(theme.palette.primary.main, 0.3)}`,
                      display: 'flex',
                      alignItems: 'center',
                      gap: 1
                    }}>
                      <MicIcon color="primary" sx={{ fontSize: 20 }} />
                      <Typography variant="body2" color="primary" sx={{ fontWeight: 500 }}>
                        {isInitializing ? 'Initializing...' : 'Listening... Speak now'}
                      </Typography>
                      <Box sx={{ 
                        width: 8, 
                        height: 8, 
                        borderRadius: '50%', 
                        backgroundColor: theme.palette.primary.main,
                        animation: 'pulse 1.5s infinite'
                      }} />
                    </Box>
                  )}

                  {/* Voice Review Panel */}
                  {showVoiceReview && (
                    <Paper
                      elevation={0}
                      className="glass-effect"
                      sx={{
                        borderRadius: 2,
                        p: 2,
                        mb: 1,
                        border: `2px solid ${theme.palette.primary.main}`,
                        backgroundColor: alpha(theme.palette.primary.main, 0.1)
                      }}
                    >
                      <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 600 }}>
                        Review Voice Input
                      </Typography>
                      <TextField
                        fullWidth
                        multiline
                        rows={3}
                        value={voiceInput}
                        onChange={(e) => setVoiceInput(e.target.value)}
                        placeholder="Your voice input will appear here..."
                        variant="outlined"
                        size="small"
                        sx={{
                          mb: 2,
                          '& .MuiOutlinedInput-root': {
                            borderRadius: 2,
                            backgroundColor: alpha(theme.palette.background.paper, 0.7)
                          }
                        }}
                      />
                      <Box sx={{ display: 'flex', gap: 1, justifyContent: 'flex-end' }}>
                        <Button
                          variant="outlined"
                          startIcon={<ClearIcon />}
                          onClick={rejectVoiceInput}
                          size="small"
                          sx={{ textTransform: 'none' }}
                        >
                          Cancel
                        </Button>
                        <Button
                          variant="contained"
                          startIcon={<CheckIcon />}
                          onClick={acceptVoiceInput}
                          size="small"
                          sx={{ textTransform: 'none' }}
                          disabled={!voiceInput.trim()}
                        >
                          Use This Text
                        </Button>
                      </Box>
                    </Paper>
                  )}

                  <Box sx={{ display: 'flex', gap: 1, alignItems: 'flex-end' }}>
                    <TextField
                      fullWidth
                      variant="outlined"
                      placeholder="Type your message or use voice input..."
                      value={input}
                      onChange={(e) => setInput(e.target.value)}
                      onKeyPress={(e) => e.key === 'Enter' && !e.shiftKey && sendMessage()}
                      disabled={isLoading}
                      multiline
                      maxRows={4}
                      size="small"
                      sx={{
                        '& .MuiOutlinedInput-root': {
                          borderRadius: 3,
                          backgroundColor: alpha(theme.palette.background.paper, 0.5)
                        }
                      }}
                    />
                    
                    {/* Voice Input Button */}
                    {speechSupported && (
                      <Tooltip title={isListening ? "Stop listening" : isInitializing ? "Initializing..." : "Start voice input"}>
                        <span>
                          <IconButton
                            onClick={isListening ? stopListening : startListening}
                            disabled={isLoading || showVoiceReview || isInitializing}
                            sx={{
                              backgroundColor: isListening 
                                ? alpha(theme.palette.error.main, 0.1)
                                : alpha(theme.palette.primary.main, 0.1),
                              border: isListening
                                ? `1px solid ${alpha(theme.palette.error.main, 0.3)}`
                                : `1px solid ${alpha(theme.palette.primary.main, 0.3)}`,
                              '&:hover': {
                                backgroundColor: isListening
                                  ? alpha(theme.palette.error.main, 0.2)
                                  : alpha(theme.palette.primary.main, 0.2)
                              },
                              '&:disabled': {
                                opacity: 0.6
                              }
                            }}
                          >
                            {isInitializing ? (
                              <MicIcon color="primary" sx={{ animation: 'pulse 1s infinite' }} />
                            ) : isListening ? (
                              <MicOffIcon color="error" />
                            ) : (
                              <MicIcon color="primary" />
                            )}
                          </IconButton>
                        </span>
                      </Tooltip>
                    )}

                    <Button
                      variant="contained"
                      color="primary"
                      endIcon={<SendIcon />}
                      onClick={sendMessage}
                      disabled={!input.trim() || isLoading}
                      className="apple-button"
                      sx={{
                        borderRadius: 3,
                        textTransform: 'none'
                      }}
                    >
                      Send
                    </Button>
                  </Box>
                </Box>
              </Box>

              {/* Agent Activity Log */}
              <Box
                sx={{
                  display: activeTab === 1 ? 'flex' : 'none',
                  flexGrow: 1,
                  overflow: 'auto',
                  flexDirection: 'column',
                  p: 2,
                  gap: 1,
                  backgroundColor: alpha(theme.palette.background.default, 0.3),
                  height: 0,
                  minHeight: 0
                }}
                className="bubble-container"
              >
                <Typography
                  variant="subtitle2"
                  sx={{
                    mb: 1,
                    color: theme.palette.text.secondary,
                    fontWeight: 500
                  }}
                >
                  Tool and Action History
                </Typography>

                {agentActions.map((action, index) => (
                  <Paper
                    key={index}
                    elevation={0}
                    className="bubble bubble-assistant fade-in"
                    sx={{
                      p: 2,
                      mb: 1,
                      borderLeft: '4px solid',
                      borderColor: 'primary.main',
                      boxShadow: '0 2px 8px rgba(0, 0, 0, 0.15)',
                      maxWidth: '95%'
                    }}
                  >
                    <Typography variant="subtitle2" fontWeight="bold">
                      {action.action}
                    </Typography>
                    <Typography
                      variant="body2"
                      component="pre"
                      sx={{
                        mt: 1,
                        p: 1,
                        bgcolor: alpha(theme.palette.background.default, 0.3),
                        borderRadius: 2,
                        overflow: 'auto',
                        fontSize: '0.85rem',
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-word'
                      }}
                    >
                      {action.details}
                    </Typography>
                    <Typography
                      variant="caption"
                      color="text.secondary"
                      sx={{ display: 'block', mt: 1, textAlign: 'right' }}
                    >
                      {new Date(action.timestamp).toLocaleTimeString()}
                    </Typography>
                  </Paper>
                ))}

                {agentActions.length === 0 && (
                  <Typography variant="body2" color="text.secondary" sx={{ fontStyle: 'italic' }}>
                    No agent activity yet. Send a message to start.
                  </Typography>
                )}

                <div ref={actionsEndRef} />
              </Box>
            </Paper>
          </Panel>

          {/* Resize Handle */}
          <PanelResizeHandle>
            <Box
              sx={{
                width: '3px',
                height: '100%',
                cursor: 'col-resize',
                transition: 'background-color 0.2s'
              }}
            />
          </PanelResizeHandle>

          {/* Right Panel - Browser View */}
          <Panel defaultSize={60} minSize={40}>
            <Paper
              elevation={0}
              className="glass-effect"
              sx={{
                height: '100%',
                borderRadius: 2,
                overflow: 'hidden',
                display: 'flex',
                flexDirection: 'column',
                ml: 0.25
              }}
            >
              {browserState ? (
                <Box sx={{
                  display: 'flex',
                  flexDirection: 'column',
                  height: '100%'
                }}>
                  {/* Browser Header */}
                  <Box sx={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    p: 1.5,
                    pl: 3,
                    borderBottom: `1px solid ${theme.palette.divider}`,
                    backgroundColor: alpha(theme.palette.background.paper, 0.6),
                    flexShrink: 0
                  }}>
                    <Typography variant="h6" sx={{ fontSize: '1.1rem', fontWeight: 500 }}>
                      Browser View
                    </Typography>
                    <Box>
                      <Button
                        variant="text"
                        size="small"
                        startIcon={<OpenInFullIcon />}
                        onClick={() => window.open(`data:image/jpeg;base64,${browserState}`, '_blank')}
                        sx={{
                          textTransform: 'none',
                          color: theme.palette.primary.main
                        }}
                      >
                        Full Size
                      </Button>
                      <Button
                        variant="text"
                        size="small"
                        startIcon={<CloseIcon />}
                        onClick={() => setBrowserState(null)}
                        sx={{
                          textTransform: 'none',
                          color: theme.palette.error.main
                        }}
                      >
                        Close
                      </Button>
                    </Box>
                  </Box>

                  {/* Browser Content */}
                  <Box sx={{
                    flexGrow: 1,
                    overflow: 'auto',
                    position: 'relative',
                    backgroundColor: alpha(theme.palette.background.default, 0.3),
                    p: 3,
                    height: 0,
                    minHeight: 0
                  }}>
                    <Paper
                      elevation={0}
                      className="fade-in"
                      sx={{
                        borderRadius: 1.5,
                        overflow: 'hidden',
                        mb: 1,
                        boxShadow: '0 2px 10px rgba(0, 0, 0, 0.15)'
                      }}
                    >
                      <img
                        src={`data:image/jpeg;base64,${browserState}`}
                        alt="Browser Screenshot"
                        className="browser-screenshot"
                        style={{
                          width: '100%',
                          height: 'auto',
                          display: 'block'
                        }}
                        onError={(e) => {
                          const target = e.target as HTMLImageElement;
                          if (target.src.includes('image/jpeg')) {
                            console.log('Trying PNG format instead');
                            target.src = `data:image/png;base64,${browserState}`;
                          }
                        }}
                      />
                    </Paper>
                    <div ref={browserEndRef} />
                  </Box>
                </Box>
              ) : (
                <Box sx={{
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  justifyContent: 'center',
                  height: '100%',
                  p: 4,
                  textAlign: 'center'
                }}>
                  <Typography variant="h6" color="text.secondary" sx={{ mb: 2 }}>
                    Browser View
                  </Typography>
                  <Typography variant="body1" color="text.secondary">
                    When the agent uses the browser, the content will appear here.
                  </Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
                    Try asking a question that requires web browsing.
                  </Typography>
                </Box>
              )}
            </Paper>
          </Panel>
        </PanelGroup>
      </Box>
    </Box>
  );
}

export default App;