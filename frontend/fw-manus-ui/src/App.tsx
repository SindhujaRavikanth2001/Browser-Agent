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
  Snackbar,
  LinearProgress,
  Chip,
  Drawer,
  CircularProgress,
  Checkbox
} from '@mui/material';
import { alpha } from '@mui/material/styles';
import SendIcon from '@mui/icons-material/Send';
import OpenInFullIcon from '@mui/icons-material/OpenInFull';
import CloseIcon from '@mui/icons-material/Close';
import MicIcon from '@mui/icons-material/Mic';
import MicOffIcon from '@mui/icons-material/MicOff';
import CheckIcon from '@mui/icons-material/Check';
import ClearIcon from '@mui/icons-material/Clear';
import ArrowBackIosIcon from '@mui/icons-material/ArrowBackIos';
import ArrowForwardIosIcon from '@mui/icons-material/ArrowForwardIos';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import PauseIcon from '@mui/icons-material/Pause';
import GetAppIcon from '@mui/icons-material/GetApp';
import RefreshIcon from '@mui/icons-material/Refresh';
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

// Slideshow types
type ScreenshotData = {
  url: string;
  screenshot: string;
  title: string;
};

type SlideshowData = {
  screenshots: ScreenshotData[];
  total_count: number;
  research_topic: string;
  is_update?: boolean;
  new_screenshots_added?: number;
};

// Download types
type DownloadFile = {
  filename: string;
  filepath: string;
  type: string;
  size: number;
  created: number;
  display_name: string;
};

// Question selection types
type QuestionData = {
  id: string;
  index: number;
  question: string;
  source: string;
  extraction_method: string;
};

type SourceData = {
  id: string;
  domain: string;
  full_url: string;
  question_count: number;
  questions: QuestionData[];
};

type UISelectionData = {
  questions: QuestionData[];
  sources: SourceData[];
  total_count: number;
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

  // Slideshow state
  const [slideshowData, setSlideshowData] = useState<SlideshowData | null>(null);
  const [currentSlideIndex, setCurrentSlideIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentImageUrl, setCurrentImageUrl] = useState<string>('');
  const [currentImageTitle, setCurrentImageTitle] = useState<string>('');
  const slideshowTimerRef = useRef<number | null>(null);

  // Download state
  const [availableFiles, setAvailableFiles] = useState<DownloadFile[]>([]);
  const [showDownloadPanel, setShowDownloadPanel] = useState(false);
  const [downloadLoading, setDownloadLoading] = useState(false);
  const [downloadNotification, setDownloadNotification] = useState({ 
    open: false, 
    message: '', 
    severity: 'success' as 'success' | 'error' | 'warning' | 'info'
  });

  // Question selection state
  const [uiSelectionData, setUISelectionData] = useState<UISelectionData | null>(null);
  const [selectedQuestionIds, setSelectedQuestionIds] = useState<Set<string>>(new Set());
  const [showQuestionSelection, setShowQuestionSelection] = useState(false);
  const [selectionMode, setSelectionMode] = useState<'initial' | 'rebrowse'>('initial');
  
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const actionsEndRef = useRef<HTMLDivElement>(null);
  const browserEndRef = useRef<HTMLDivElement>(null);

  // Update voiceInputRef whenever voiceInput changes
  useEffect(() => {
    voiceInputRef.current = voiceInput;
  }, [voiceInput]);

  // Download functions
  const fetchAvailableFiles = async () => {
    try {
      const response = await fetch('/api/research-files');
      const data = await response.json();
      setAvailableFiles(data.files || []);
    } catch (error) {
      console.error('Error fetching files:', error);
    }
  };

  const downloadFile = async (filename: string) => {
    try {
      setDownloadLoading(true);
      const response = await fetch(`/api/download/${filename}`);
      
      if (response.ok) {
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.style.display = 'none';
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
        
        // Show success notification
        showDownloadNotification(`Successfully downloaded: ${filename}`, 'success');
      } else {
        showDownloadNotification('Download failed. Please try again.', 'error');
        console.error('Download failed:', response.statusText);
      }
    } catch (error) {
      showDownloadNotification('Download error. Please check your connection.', 'error');
      console.error('Error downloading file:', error);
    } finally {
      setDownloadLoading(false);
    }
  };

  const downloadLatestFile = async (fileType: string) => {
    try {
      setDownloadLoading(true);
      const response = await fetch(`/api/download-latest/${fileType}`);
      
      if (response.ok) {
        const blob = await response.blob();
        const filename = response.headers.get('content-disposition')
          ?.split('filename=')[1]?.replace(/"/g, '') || `latest_${fileType}.txt`;
        
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.style.display = 'none';
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
        
        // Show success notification
        showDownloadNotification(`Successfully downloaded: ${filename}`, 'success');
      } else {
        showDownloadNotification(`No ${fileType.replace('_', ' ')} files found.`, 'warning');
        console.error('Download failed:', response.statusText);
      }
    } catch (error) {
      showDownloadNotification('Download error. Please check your connection.', 'error');
      console.error('Error downloading latest file:', error);
    } finally {
      setDownloadLoading(false);
    }
  };

  const formatFileSize = (bytes: number) => {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  const formatDate = (timestamp: number) => {
    return new Date(timestamp * 1000).toLocaleString();
  };

  const showDownloadNotification = (message: string, severity: 'success' | 'error' | 'warning' | 'info' = 'success') => {
    setDownloadNotification({ open: true, message, severity });
  };

  // Question selection functions
  const handleQuestionToggle = (questionId: string) => {
    const newSelected = new Set(selectedQuestionIds);
    
    if (newSelected.has(questionId)) {
      newSelected.delete(questionId);
    } else {
      // Check if we've reached the maximum (30 questions)
      if (newSelected.size >= 30) {
        showDownloadNotification('Maximum 30 questions can be selected', 'warning');
        return;
      }
      newSelected.add(questionId);
    }
    
    setSelectedQuestionIds(newSelected);
  };

  const handleSelectAllFromSource = (sourceId: string) => {
    if (!uiSelectionData) return;
    
    const source = uiSelectionData.sources.find(s => s.id === sourceId);
    if (!source) return;
    
    const newSelected = new Set(selectedQuestionIds);
    let addedCount = 0;
    
    for (const question of source.questions) {
      if (!newSelected.has(question.id) && newSelected.size + addedCount < 30) {
        newSelected.add(question.id);
        addedCount++;
      }
    }
    
    if (addedCount === 0 && newSelected.size >= 30) {
      showDownloadNotification('Maximum 30 questions can be selected', 'warning');
    }
    
    setSelectedQuestionIds(newSelected);
  };

  const handleDeselectAllFromSource = (sourceId: string) => {
    if (!uiSelectionData) return;
    
    const source = uiSelectionData.sources.find(s => s.id === sourceId);
    if (!source) return;
    
    const newSelected = new Set(selectedQuestionIds);
    for (const question of source.questions) {
      newSelected.delete(question.id);
    }
    
    setSelectedQuestionIds(newSelected);
  };

  const submitQuestionSelection = () => {
    if (selectedQuestionIds.size === 0) {
      showDownloadNotification('Please select at least one question', 'warning');
      return;
    }

    const selectionData = {
      selected_questions: Array.from(selectedQuestionIds)
    };

    // Send selection via WebSocket or HTTP
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ 
        content: JSON.stringify(selectionData)
      }));
    } else {
      fetch('/api/message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          content: JSON.stringify(selectionData)
        })
      });
    }

    // Close selection panel
    setShowQuestionSelection(false);
    setSelectedQuestionIds(new Set());
    setUISelectionData(null);
    setIsLoading(true);
  };

  const handleContinueWithoutSelection = () => {
    // Send continue command
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ content: 'Continue' }));
    } else {
      fetch('/api/message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: 'Continue' })
      });
    }

    setShowQuestionSelection(false);
    setSelectedQuestionIds(new Set());
    setUISelectionData(null);
    setIsLoading(true);
  };

  const handleRebrowseForMore = () => {
    // Send rebrowse command
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ content: 'Rebrowse' }));
    } else {
      fetch('/api/message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: 'Rebrowse' })
      });
    }
    
    setSelectionMode('rebrowse');
    setIsLoading(true);
    // Keep the selection panel open to show new questions when they arrive
  };

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

  // Slideshow control functions
  const nextSlide = () => {
    if (!slideshowData || slideshowData.screenshots.length === 0) return;
    
    const nextIndex = (currentSlideIndex + 1) % slideshowData.screenshots.length;
    setCurrentSlideIndex(nextIndex);
    
    const nextScreenshot = slideshowData.screenshots[nextIndex];
    setBrowserState(nextScreenshot.screenshot);
    setCurrentImageUrl(nextScreenshot.url);
    setCurrentImageTitle(nextScreenshot.title);
  };

  const previousSlide = () => {
    if (!slideshowData || slideshowData.screenshots.length === 0) return;
    
    const prevIndex = currentSlideIndex === 0 
      ? slideshowData.screenshots.length - 1 
      : currentSlideIndex - 1;
    setCurrentSlideIndex(prevIndex);
    
    const prevScreenshot = slideshowData.screenshots[prevIndex];
    setBrowserState(prevScreenshot.screenshot);
    setCurrentImageUrl(prevScreenshot.url);
    setCurrentImageTitle(prevScreenshot.title);
  };

  const togglePlayPause = () => {
    if (isPlaying) {
      // Pause slideshow
      if (slideshowTimerRef.current) {
        clearInterval(slideshowTimerRef.current);
        slideshowTimerRef.current = null;
      }
      setIsPlaying(false);
    } else {
      // Start slideshow
      slideshowTimerRef.current = setInterval(() => {
        nextSlide();
      }, 3000); // Change slide every 3 seconds
      setIsPlaying(true);
    }
  };

  const goToSlide = (index: number) => {
    if (!slideshowData || slideshowData.screenshots.length === 0) return;
    
    setCurrentSlideIndex(index);
    const screenshot = slideshowData.screenshots[index];
    setBrowserState(screenshot.screenshot);
    setCurrentImageUrl(screenshot.url);
    setCurrentImageTitle(screenshot.title);
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
        
        // Handle UI selection data
        if (data.ui_selection_data) {
          console.log('Received UI selection data:', data.ui_selection_data);
          setUISelectionData(data.ui_selection_data);
          setShowQuestionSelection(true);
          setSelectionMode('initial');
        }
        
        // Alternative: Check for UI selection trigger flag
        if (data.show_question_selection) {
          console.log('Received show_question_selection flag');
          setShowQuestionSelection(true);
        }
        
        // Also check for UI selection trigger in message content
        if (data.content && data.content.includes('[UI_SELECTION_TRIGGER]')) {
          console.log('Detected UI selection trigger in message content');
          // The UI selection data should be in the same message
          if (data.ui_selection_data) {
            setUISelectionData(data.ui_selection_data);
            setShowQuestionSelection(true);
            setSelectionMode('initial');
          }
        }
        
        // Handle screenshot in agent message response
        if (data.base64_image) {
          console.log('Received screenshot with agent message');
          setBrowserState(data.base64_image);
          setCurrentImageUrl(data.image_url || '');
          setCurrentImageTitle(data.image_title || '');
        }

        // NEW: Detect when research package is completed and files are generated
        if (data.content) {
          const content = data.content.toLowerCase();
          
          // Check if this message indicates files were generated
          if (content.includes('research package complete') || 
              content.includes('exported to') || 
              content.includes('package exported') ||
              content.includes('research_outputs/')) {
            
            // Show notification that files are ready for download
            showDownloadNotification(
              'Research files generated! Click the download button in the header to access them.',
              'success'
            );
            
            // Automatically refresh available files
            setTimeout(() => {
              fetchAvailableFiles();
            }, 1000);
          }
        }
      } else if (data.type === 'slideshow_data') {
        // ENHANCED: Handle slideshow data updates
        console.log('Received slideshow data:', data);
        
        // If this is an update to existing slideshow
        if (data.is_update && slideshowData) {
          console.log(`Slideshow update: Added ${data.new_screenshots_added || 0} new screenshots`);
          
          // Update existing slideshow data safely
          setSlideshowData(prevData => {
            if (!prevData) {
              // If prevData is null, treat as initial setup
              return {
                screenshots: data.screenshots || [],
                total_count: data.total_count || 0,
                research_topic: data.research_topic || ''
              };
            }
            
            return {
              ...prevData,
              screenshots: data.screenshots || prevData.screenshots || [],
              total_count: data.total_count || prevData.total_count || 0,
              research_topic: data.research_topic || prevData.research_topic || ''
            };
          });
          
          // Show a brief notification about the update
          if (data.new_screenshots_added > 0) {
            // You could add a toast notification here
            console.log(`✅ Added ${data.new_screenshots_added} new screenshots to slideshow`);
          }
          
          // Don't reset slide index for updates - user might be viewing specific slides
          // But ensure index is valid
          if (currentSlideIndex >= (data.screenshots?.length || 0)) {
            setCurrentSlideIndex(Math.max(0, (data.screenshots?.length || 1) - 1));
          }
          
        } else {
          // Initial slideshow setup
          console.log('Setting up initial slideshow with', data.screenshots?.length || 0, 'screenshots');
          setSlideshowData({
            screenshots: data.screenshots || [],
            total_count: data.total_count || 0,
            research_topic: data.research_topic || ''
          });
          setCurrentSlideIndex(0);
        }
        
        // Set the current screenshot (first for new, or maintain current for updates)
        if (data.screenshots && data.screenshots.length > 0) {
          let targetIndex = 0;
          
          // For updates, stay on current slide if valid, or go to latest
          if (data.is_update && slideshowData) {
            if (currentSlideIndex < data.screenshots.length) {
              targetIndex = currentSlideIndex;
            } else {
              targetIndex = data.screenshots.length - 1; // Go to latest
            }
          }
          
          const targetScreenshot = data.screenshots[targetIndex];
          if (targetScreenshot) {
            setBrowserState(targetScreenshot.screenshot);
            setCurrentImageUrl(targetScreenshot.url || '');
            setCurrentImageTitle(targetScreenshot.title || '');
            setCurrentSlideIndex(targetIndex);
          }
        }
        
        // Handle UI selection data in slideshow updates
        if (data.ui_selection_data) {
          console.log('Received updated UI selection data with slideshow');
          setUISelectionData(data.ui_selection_data);
          setShowQuestionSelection(true);
          setSelectionMode('rebrowse');
        }
        
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
          setCurrentImageUrl(data.url || '');
          setCurrentImageTitle(data.title || '');
          console.log('Screenshot displayed in browser view');
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

  // Clean up slideshow timer on unmount
  useEffect(() => {
    return () => {
      if (slideshowTimerRef.current) {
        clearInterval(slideshowTimerRef.current);
      }
    };
  }, []);

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
          
          // Handle UI selection data from HTTP API
          if (data.ui_selection_data) {
            console.log('Received UI selection data from HTTP API');
            setUISelectionData(data.ui_selection_data);
            setShowQuestionSelection(true);
            setSelectionMode('initial');
          }
          
          // Also check for show_question_selection flag
          if (data.show_question_selection) {
            console.log('Received show_question_selection flag from HTTP API');
            setShowQuestionSelection(true);
          }
          
          // Check for UI selection trigger in response content
          if (data.response && data.response.includes('[UI_SELECTION_TRIGGER]')) {
            console.log('Detected UI selection trigger in HTTP response');
            if (data.ui_selection_data) {
              setUISelectionData(data.ui_selection_data);
              setShowQuestionSelection(true);
              setSelectionMode('initial');
            }
          }
          
          // Handle slideshow data from HTTP API
          if (data.slideshow_data) {
            console.log('Received slideshow data from HTTP API');
            setSlideshowData(data.slideshow_data);
            setCurrentSlideIndex(0);
          }
          
          // Handle screenshot from HTTP API response
          if (data.base64_image) {
            console.log('Received screenshot from HTTP API');
            setBrowserState(data.base64_image);
            setCurrentImageUrl(data.image_url || '');
            setCurrentImageTitle(data.image_title || '');
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

  // Download Panel Component
  const DownloadPanel = () => (
    <Drawer
      anchor="right"
      open={showDownloadPanel}
      onClose={() => setShowDownloadPanel(false)}
      sx={{
        '& .MuiDrawer-paper': {
          width: 400,
          maxWidth: '90vw',
          p: 0
        }
      }}
    >
      <Box sx={{ p: 3, height: '100%', overflow: 'auto' }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
          <Typography variant="h6" fontWeight="600">
            Download Research Files
          </Typography>
          <IconButton onClick={() => setShowDownloadPanel(false)}>
            <CloseIcon />
          </IconButton>
        </Box>

        {/* Quick Download Section */}
        <Paper elevation={0} sx={{ p: 2, mb: 3, backgroundColor: alpha(theme.palette.primary.main, 0.05) }}>
          <Typography variant="subtitle2" sx={{ mb: 2, fontWeight: 600 }}>
            Quick Downloads
          </Typography>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            <Button
              variant="outlined"
              size="small"
              onClick={() => downloadLatestFile('complete_research_package')}
              disabled={downloadLoading}
              startIcon={<GetAppIcon />}
              sx={{ textTransform: 'none' }}
            >
              Latest Research Package
            </Button>
            <Button
              variant="outlined"
              size="small"
              onClick={() => downloadLatestFile('chat_history')}
              disabled={downloadLoading}
              startIcon={<GetAppIcon />}
              sx={{ textTransform: 'none' }}
            >
              Latest Chat History
            </Button>
          </Box>
        </Paper>

        {/* All Files Section */}
        <Box sx={{ mb: 2, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Typography variant="subtitle2" fontWeight="600">
            All Files ({availableFiles.length})
          </Typography>
          <Button
            size="small"
            onClick={fetchAvailableFiles}
            startIcon={<RefreshIcon />}
            sx={{ textTransform: 'none' }}
          >
            Refresh
          </Button>
        </Box>

        {availableFiles.length === 0 ? (
          <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'center', py: 4 }}>
            No research files found. Complete a research workflow to generate files.
          </Typography>
        ) : (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            {availableFiles.map((file, index) => (
              <Paper
                key={index}
                elevation={0}
                sx={{
                  p: 2,
                  border: `1px solid ${theme.palette.divider}`,
                  borderRadius: 2,
                  '&:hover': {
                    backgroundColor: alpha(theme.palette.primary.main, 0.02)
                  }
                }}
              >
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 1 }}>
                  <Box sx={{ flexGrow: 1, mr: 1 }}>
                    <Typography variant="body2" fontWeight="500" sx={{ mb: 0.5 }}>
                      {file.display_name}
                    </Typography>
                    <Box sx={{ display: 'flex', gap: 1, mb: 1 }}>
                      <Chip
                        label={file.type.replace('_', ' ')}
                        size="small"
                        sx={{
                          fontSize: '0.7rem',
                          height: '18px',
                          backgroundColor: file.type === 'research_package' 
                            ? alpha(theme.palette.success.main, 0.1)
                            : file.type === 'chat_history'
                            ? alpha(theme.palette.info.main, 0.1)
                            : alpha(theme.palette.grey[500], 0.1)
                        }}
                      />
                      <Typography variant="caption" color="text.secondary">
                        {formatFileSize(file.size)}
                      </Typography>
                    </Box>
                    <Typography variant="caption" color="text.secondary">
                      {formatDate(file.created)}
                    </Typography>
                  </Box>
                  <IconButton
                    size="small"
                    onClick={() => downloadFile(file.filename)}
                    disabled={downloadLoading}
                    sx={{
                      backgroundColor: alpha(theme.palette.primary.main, 0.1),
                      '&:hover': {
                        backgroundColor: alpha(theme.palette.primary.main, 0.2)
                      }
                    }}
                  >
                    <GetAppIcon fontSize="small" />
                  </IconButton>
                </Box>
              </Paper>
            ))}
          </Box>
        )}

        {downloadLoading && (
          <Box sx={{ display: 'flex', justifyContent: 'center', mt: 2 }}>
            <CircularProgress size={24} />
          </Box>
        )}
      </Box>
    </Drawer>
  );

  // Question Selection Panel Component
  const QuestionSelectionPanel = () => (
    <Drawer
      anchor="bottom"
      open={showQuestionSelection}
      onClose={() => setShowQuestionSelection(false)}
      sx={{
        '& .MuiDrawer-paper': {
          height: '70vh',
          maxHeight: '600px',
          p: 0
        }
      }}
    >
      <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
        {/* Header */}
        <Box sx={{ 
          p: 3, 
          borderBottom: `1px solid ${theme.palette.divider}`,
          backgroundColor: alpha(theme.palette.background.paper, 0.9),
          flexShrink: 0
        }}>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
            <Typography variant="h6" fontWeight="600">
              Select Research Questions
              {selectionMode === 'rebrowse' && (
                <Chip
                  label="Updated"
                  size="small"
                  color="success"
                  sx={{ ml: 1 }}
                />
              )}
            </Typography>
            <IconButton onClick={() => setShowQuestionSelection(false)}>
              <CloseIcon />
            </IconButton>
          </Box>
          
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
            <Typography variant="body2" color="text.secondary">
              Select up to 30 questions from the found research sources
            </Typography>
            <Chip
              label={`${selectedQuestionIds.size}/30 selected`}
              size="small"
              color={selectedQuestionIds.size >= 30 ? 'error' : 'primary'}
            />
          </Box>

          {/* Action buttons */}
          <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
            <Button
              variant="contained"
              onClick={submitQuestionSelection}
              disabled={selectedQuestionIds.size === 0 || isLoading}
              sx={{ textTransform: 'none' }}
            >
              Continue with {selectedQuestionIds.size} Questions
            </Button>
            <Button
              variant="outlined"
              onClick={handleContinueWithoutSelection}
              disabled={isLoading}
              sx={{ textTransform: 'none' }}
            >
              Continue without Selection
            </Button>
            {uiSelectionData && uiSelectionData.sources.length > 0 && (
              <Button
                variant="text"
                onClick={handleRebrowseForMore}
                disabled={isLoading}
                sx={{ textTransform: 'none' }}
              >
                Find More Questions
              </Button>
            )}
          </Box>

          {isLoading && (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 1 }}>
              <CircularProgress size={16} />
              <Typography variant="caption" color="text.secondary">
                Processing your selection...
              </Typography>
            </Box>
          )}
        </Box>

        {/* Questions content */}
        <Box sx={{ flexGrow: 1, overflow: 'auto', p: 2 }}>
          {uiSelectionData && uiSelectionData.sources.length > 0 ? (
            uiSelectionData.sources.map((source, sourceIndex) => (
              <Paper
                key={source.id}
                elevation={0}
                sx={{
                  mb: 3,
                  border: `1px solid ${theme.palette.divider}`,
                  borderRadius: 2,
                  overflow: 'hidden'
                }}
              >
                {/* Source header */}
                <Box sx={{
                  p: 2,
                  backgroundColor: alpha(theme.palette.primary.main, 0.05),
                  borderBottom: `1px solid ${theme.palette.divider}`
                }}>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <Box>
                      <Typography variant="subtitle1" fontWeight="600">
                        {source.domain}
                      </Typography>
                      <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                        {source.full_url}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {source.question_count} questions found
                      </Typography>
                    </Box>
                    <Box sx={{ display: 'flex', gap: 1 }}>
                      <Button
                        size="small"
                        onClick={() => handleSelectAllFromSource(source.id)}
                        disabled={selectedQuestionIds.size >= 30}
                        sx={{ textTransform: 'none' }}
                      >
                        Select All
                      </Button>
                      <Button
                        size="small"
                        variant="outlined"
                        onClick={() => handleDeselectAllFromSource(source.id)}
                        sx={{ textTransform: 'none' }}
                      >
                        Deselect All
                      </Button>
                    </Box>
                  </Box>
                </Box>

                {/* Questions list */}
                <Box sx={{ p: 2 }}>
                  {source.questions.map((question, questionIndex) => (
                    <Box
                      key={question.id}
                      sx={{
                        display: 'flex',
                        alignItems: 'flex-start',
                        gap: 2,
                        p: 1.5,
                        borderRadius: 1,
                        '&:hover': {
                          backgroundColor: alpha(theme.palette.primary.main, 0.02)
                        },
                        borderBottom: questionIndex < source.questions.length - 1 
                          ? `1px solid ${alpha(theme.palette.divider, 0.5)}` 
                          : 'none'
                      }}
                    >
                      <Checkbox
                        checked={selectedQuestionIds.has(question.id)}
                        onChange={() => handleQuestionToggle(question.id)}
                        disabled={!selectedQuestionIds.has(question.id) && selectedQuestionIds.size >= 30}
                        sx={{
                          mt: -0.5,
                          '&.Mui-disabled': {
                            color: theme.palette.action.disabled
                          }
                        }}
                      />
                      <Box sx={{ flexGrow: 1 }}>
                        <Typography 
                          variant="body2" 
                          sx={{ 
                            fontWeight: selectedQuestionIds.has(question.id) ? 600 : 400,
                            color: selectedQuestionIds.has(question.id) 
                              ? theme.palette.primary.main 
                              : theme.palette.text.primary
                          }}
                        >
                          {question.question}
                        </Typography>
                        <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: 'block' }}>
                          Method: {question.extraction_method.replace('_', ' ')}
                        </Typography>
                      </Box>
                    </Box>
                  ))}
                </Box>
              </Paper>
            ))
          ) : (
            <Box sx={{ textAlign: 'center', py: 4 }}>
              <Typography variant="body1" color="text.secondary">
                No questions available for selection
              </Typography>
            </Box>
          )}
        </Box>
      </Box>
    </Drawer>
  );

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
          
          {/* Download Button */}
          <Box sx={{ ml: 'auto', display: 'flex', gap: 1 }}>
            {/* Debug button to test question selection UI */}
            <Tooltip title="Test Question Selection UI (Debug)">
              <IconButton
                onClick={() => {
                  // Create mock UI selection data for testing
                  const mockUISelectionData = {
                    questions: [
                      { id: 'q_1', index: 0, question: 'How satisfied are you with our service?', source: 'https://example.com/survey1', extraction_method: 'regex_pattern' },
                      { id: 'q_2', index: 1, question: 'What is your age group?', source: 'https://example.com/survey1', extraction_method: 'simple_pattern' },
                      { id: 'q_3', index: 2, question: 'How often do you use our product?', source: 'https://example.com/survey2', extraction_method: 'llm_extraction' },
                      { id: 'q_4', index: 3, question: 'Would you recommend us to others?', source: 'https://example.com/survey2', extraction_method: 'regex_pattern' },
                    ],
                    sources: [
                      {
                        id: 'source_1',
                        domain: 'example.com',
                        full_url: 'https://example.com/survey1',
                        question_count: 2,
                        questions: [
                          { id: 'q_1', index: 0, question: 'How satisfied are you with our service?', source: 'https://example.com/survey1', extraction_method: 'regex_pattern' },
                          { id: 'q_2', index: 1, question: 'What is your age group?', source: 'https://example.com/survey1', extraction_method: 'simple_pattern' }
                        ]
                      },
                      {
                        id: 'source_2',
                        domain: 'example.com',
                        full_url: 'https://example.com/survey2',
                        question_count: 2,
                        questions: [
                          { id: 'q_3', index: 2, question: 'How often do you use our product?', source: 'https://example.com/survey2', extraction_method: 'llm_extraction' },
                          { id: 'q_4', index: 3, question: 'Would you recommend us to others?', source: 'https://example.com/survey2', extraction_method: 'regex_pattern' }
                        ]
                      }
                    ],
                    total_count: 4
                  };
                  
                  setUISelectionData(mockUISelectionData);
                  setShowQuestionSelection(true);
                  setSelectionMode('initial');
                  console.log('Triggered test question selection UI');
                }}
                sx={{
                  backgroundColor: alpha(theme.palette.warning.main, 0.1),
                  '&:hover': {
                    backgroundColor: alpha(theme.palette.warning.main, 0.2)
                  }
                }}
              >
                <Typography variant="caption" sx={{ fontSize: '10px' }}>TEST</Typography>
              </IconButton>
            </Tooltip>
            
            <Tooltip title="Download Research Files">
              <IconButton
                onClick={() => {
                  fetchAvailableFiles();
                  setShowDownloadPanel(true);
                }}
                sx={{
                  backgroundColor: alpha(theme.palette.primary.main, 0.1),
                  '&:hover': {
                    backgroundColor: alpha(theme.palette.primary.main, 0.2)
                  }
                }}
              >
                <GetAppIcon />
              </IconButton>
            </Tooltip>
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

      {/* Download Notification Snackbar */}
      <Snackbar
        open={downloadNotification.open}
        autoHideDuration={6000}
        onClose={() => setDownloadNotification({ ...downloadNotification, open: false })}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
      >
        <Alert 
          onClose={() => setDownloadNotification({ ...downloadNotification, open: false })} 
          severity={downloadNotification.severity} 
          sx={{ width: '100%' }}
          action={
            downloadNotification.severity === 'success' && (
              <Button 
                color="inherit" 
                size="small" 
                onClick={() => {
                  fetchAvailableFiles();
                  setShowDownloadPanel(true);
                  setDownloadNotification({ ...downloadNotification, open: false });
                }}
              >
                DOWNLOAD
              </Button>
            )
          }
        >
          {downloadNotification.message}
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

          {/* Right Panel - Enhanced Browser View with Slideshow */}
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
                  {/* Enhanced Browser Header with Slideshow Controls */}
                  <Box sx={{
                    display: 'flex',
                    flexDirection: 'column',
                    borderBottom: `1px solid ${theme.palette.divider}`,
                    backgroundColor: alpha(theme.palette.background.paper, 0.6),
                    flexShrink: 0
                  }}>
                    {/* Main header */}
                    <Box sx={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      p: 1.5,
                      pl: 3
                    }}>
                      <Box>
                        <Typography variant="h6" sx={{ fontSize: '1.1rem', fontWeight: 500 }}>
                          Browser View
                          {slideshowData && (
                            <Chip
                              label={`${slideshowData.total_count} websites`}
                              size="small"
                              sx={{ 
                                ml: 1, 
                                fontSize: '0.75rem',
                                animation: slideshowData.is_update ? 'pulse 2s ease-in-out' : 'none'
                              }}
                            />
                          )}
                        </Typography>
                        {currentImageTitle && (
                          <Typography variant="caption" sx={{ display: 'block', opacity: 0.7, mt: 0.5 }}>
                            {currentImageTitle}
                          </Typography>
                        )}
                        {slideshowData?.research_topic && (
                          <Typography variant="caption" sx={{ 
                            display: 'block', 
                            opacity: 0.6, 
                            fontStyle: 'italic',
                            mt: 0.25 
                          }}>
                            Research: {slideshowData.research_topic}
                          </Typography>
                        )}
                      </Box>
                      <Box>
                        <Button
                          variant="text"
                          size="small"
                          startIcon={<OpenInFullIcon />}
                          onClick={() => {
                            if (currentImageUrl) {
                              window.open(currentImageUrl, '_blank');
                            } else {
                              window.open(`data:image/jpeg;base64,${browserState}`, '_blank');
                            }
                          }}
                          sx={{
                            textTransform: 'none',
                            color: theme.palette.primary.main
                          }}
                        >
                          {currentImageUrl ? 'Visit Site' : 'Full Size'}
                        </Button>
                        <Button
                          variant="text"
                          size="small"
                          startIcon={<CloseIcon />}
                          onClick={() => {
                            setBrowserState(null);
                            setSlideshowData(null);
                            setCurrentImageUrl('');
                            setCurrentImageTitle('');
                            if (slideshowTimerRef.current) {
                              clearInterval(slideshowTimerRef.current);
                              setIsPlaying(false);
                            }
                          }}
                          sx={{
                            textTransform: 'none',
                            color: theme.palette.error.main
                          }}
                        >
                          Close
                        </Button>
                      </Box>
                    </Box>

                    {/* Enhanced Slideshow Controls */}
                    {slideshowData && slideshowData.screenshots.length > 1 && (
                      <Box sx={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        gap: 1,
                        p: 1,
                        backgroundColor: alpha(theme.palette.background.default, 0.1)
                      }}>
                        <IconButton
                          size="small"
                          onClick={previousSlide}
                          disabled={slideshowData.screenshots.length <= 1}
                        >
                          <ArrowBackIosIcon fontSize="small" />
                        </IconButton>
                        
                        <IconButton
                          size="small"
                          onClick={togglePlayPause}
                          sx={{
                            backgroundColor: isPlaying ? alpha(theme.palette.error.main, 0.1) : alpha(theme.palette.primary.main, 0.1),
                            '&:hover': {
                              backgroundColor: isPlaying ? alpha(theme.palette.error.main, 0.2) : alpha(theme.palette.primary.main, 0.2)
                            }
                          }}
                        >
                          {isPlaying ? <PauseIcon fontSize="small" /> : <PlayArrowIcon fontSize="small" />}
                        </IconButton>
                        
                        <Typography variant="caption" sx={{ mx: 1 }}>
                          {currentSlideIndex + 1} / {slideshowData.screenshots.length}
                        </Typography>
                        
                        {slideshowData.is_update && (
                          <Chip
                            label="Updated"
                            size="small"
                            color="success"
                            sx={{ 
                              fontSize: '0.7rem', 
                              height: '20px',
                              animation: 'fadeIn 1s ease-in'
                            }}
                          />
                        )}
                        
                        <IconButton
                          size="small"
                          onClick={nextSlide}
                          disabled={slideshowData.screenshots.length <= 1}
                        >
                          <ArrowForwardIosIcon fontSize="small" />
                        </IconButton>
                      </Box>
                    )}

                    {/* Enhanced Progress bar for slideshow */}
                    {slideshowData && slideshowData.screenshots.length > 1 && (
                      <LinearProgress
                        variant="determinate"
                        value={(currentSlideIndex + 1) / slideshowData.screenshots.length * 100}
                        sx={{ 
                          height: 3,
                          boxShadow: slideshowData.is_update ? '0 0 8px rgba(46, 196, 72, 0.4)' : 'none',
                          transition: 'box-shadow 2s ease-out'
                        }}
                      />
                    )}
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
                        boxShadow: '0 2px 10px rgba(0, 0, 0, 0.15)',
                        position: 'relative'
                      }}
                    >
                      <img
                        src={`data:image/jpeg;base64,${browserState}`}
                        alt="Browser Screenshot"
                        className="browser-screenshot"
                        style={{
                          width: '100%',
                          height: 'auto',
                          display: 'block',
                          cursor: currentImageUrl ? 'pointer' : 'default'
                        }}
                        onClick={() => {
                          if (currentImageUrl) {
                            window.open(currentImageUrl, '_blank');
                          }
                        }}
                        onError={(e) => {
                          const target = e.target as HTMLImageElement;
                          if (target.src.includes('image/jpeg')) {
                            console.log('Trying PNG format instead');
                            target.src = `data:image/png;base64,${browserState}`;
                          }
                        }}
                      />
                      
                      {/* URL overlay */}
                      {currentImageUrl && (
                        <Box sx={{
                          position: 'absolute',
                          bottom: 0,
                          left: 0,
                          right: 0,
                          background: 'linear-gradient(transparent, rgba(0,0,0,0.7))',
                          color: 'white',
                          p: 1,
                          fontSize: '0.75rem'
                        }}>
                          <Typography variant="caption" sx={{ 
                            wordBreak: 'break-all',
                            opacity: 0.9
                          }}>
                            {currentImageUrl}
                          </Typography>
                        </Box>
                      )}
                    </Paper>

                    {/* Thumbnail navigation for slideshow */}
                    {slideshowData && slideshowData.screenshots.length > 1 && (
                      <Box sx={{
                        display: 'flex',
                        gap: 1,
                        mt: 2,
                        overflowX: 'auto',
                        pb: 1
                      }}>
                        {slideshowData.screenshots.map((screenshot, index) => (
                          <Paper
                            key={index}
                            elevation={currentSlideIndex === index ? 3 : 1}
                            sx={{
                              minWidth: 80,
                              height: 60,
                              borderRadius: 1,
                              overflow: 'hidden',
                              cursor: 'pointer',
                              border: currentSlideIndex === index 
                                ? `2px solid ${theme.palette.primary.main}` 
                                : '2px solid transparent',
                              transition: 'all 0.2s ease',
                              '&:hover': {
                                transform: 'scale(1.05)',
                                boxShadow: theme.shadows[4]
                              }
                            }}
                            onClick={() => goToSlide(index)}
                          >
                            <img
                              src={`data:image/jpeg;base64,${screenshot.screenshot}`}
                              alt={`Screenshot ${index + 1}`}
                              style={{
                                width: '100%',
                                height: '100%',
                                objectFit: 'cover'
                              }}
                            />
                          </Paper>
                        ))}
                      </Box>
                    )}
                    
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
                    Try asking a question that requires web browsing or start a research workflow.
                  </Typography>
                </Box>
              )}
            </Paper>
          </Panel>
        </PanelGroup>
      </Box>

      {/* Download Panel */}
      <DownloadPanel />

      {/* Question Selection Panel */}
      <QuestionSelectionPanel />
    </Box>
  );
}

export default App;