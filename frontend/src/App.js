import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import './App.css';

const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

function App() {
  const [userId, setUserId] = useState('');
  const [organizationId, setOrganizationId] = useState('');
  const [teamId, setTeamId] = useState('');
  const [validatedUserId, setValidatedUserId] = useState('');
  const [validatedOrganizationId, setValidatedOrganizationId] = useState('');
  const [validatedTeamId, setValidatedTeamId] = useState('');
  const [userRole, setUserRole] = useState('');
  const [currentChatId, setCurrentChatId] = useState(null);
  const [currentChatSharingLevel, setCurrentChatSharingLevel] = useState('private');
  const [messages, setMessages] = useState([]);
  const [inputMessage, setInputMessage] = useState('');
  const [loading, setLoading] = useState(false);
  const [userChats, setUserChats] = useState([]);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [validating, setValidating] = useState(false);
  const [uploadingPdf, setUploadingPdf] = useState(false);
  const [pdfUploadStatus, setPdfUploadStatus] = useState(null);
  const [uploadedPdfs, setUploadedPdfs] = useState([]);
  const [pendingPdfDocumentId, setPendingPdfDocumentId] = useState(null);
  const [organizations, setOrganizations] = useState([]);
  const [organizationUsers, setOrganizationUsers] = useState([]);
  const [organizationTeams, setOrganizationTeams] = useState([]);
  const [showOrgSuggestions, setShowOrgSuggestions] = useState(false);
  const [showUserSuggestions, setShowUserSuggestions] = useState(false);
  const [showTeamSuggestions, setShowTeamSuggestions] = useState(false);
  const messagesEndRef = useRef(null);
  const fileInputRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  useEffect(() => {
    if (currentChatId) {
      loadMessages();
      loadChatPdfs();
    } else {
      setUploadedPdfs([]);
    }
  }, [currentChatId]);

  useEffect(() => {
    // Clear PDF upload status after 5 seconds
    if (pdfUploadStatus) {
      const timer = setTimeout(() => {
        setPdfUploadStatus(null);
      }, 5000);
      return () => clearTimeout(timer);
    }
  }, [pdfUploadStatus]);

  useEffect(() => {
    if (validatedUserId) {
      loadUserChats();
    }
  }, [validatedUserId]);

  useEffect(() => {
    // Load all organizations for auto-complete
    loadOrganizations();
  }, []);

  useEffect(() => {
    // When organization changes, load users and teams
    if (organizationId.trim()) {
      loadOrganizationUsers(organizationId.trim());
      loadOrganizationTeams(organizationId.trim());
      setShowOrgSuggestions(false);
    } else {
      setOrganizationUsers([]);
      setOrganizationTeams([]);
    }
  }, [organizationId]);

  const loadOrganizations = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/api/organizations`);
      setOrganizations(response.data);
    } catch (error) {
      console.error('Error loading organizations:', error);
    }
  };

  const loadOrganizationUsers = async (orgId) => {
    try {
      const response = await axios.get(`${API_BASE_URL}/api/organizations/${orgId}/users`);
      setOrganizationUsers(response.data);
    } catch (error) {
      console.error('Error loading organization users:', error);
      setOrganizationUsers([]);
    }
  };

  const loadOrganizationTeams = async (orgId) => {
    try {
      const response = await axios.get(`${API_BASE_URL}/api/organizations/${orgId}/teams`);
      setOrganizationTeams(response.data);
    } catch (error) {
      console.error('Error loading organization teams:', error);
      setOrganizationTeams([]);
    }
  };

  const loadMessages = async () => {
    if (!currentChatId) return;
    
    try {
      const response = await axios.get(`${API_BASE_URL}/api/chat/${currentChatId}/messages`);
      setMessages(response.data);
    } catch (error) {
      console.error('Error loading messages:', error);
    }
  };

  const loadUserChats = async () => {
    if (!validatedUserId) return;
    
    try {
      const response = await axios.get(`${API_BASE_URL}/api/user/${validatedUserId}/chats/preview`);
      setUserChats(response.data);
    } catch (error) {
      console.error('Error loading user chats:', error);
      alert('Error loading chats. Please check the user ID and try again.');
    }
  };

  const handleUserSubmit = async (e) => {
    e?.preventDefault();
    
    const trimmedUserId = userId.trim();
    const trimmedOrganizationId = organizationId.trim();
    const trimmedTeamId = teamId.trim();
    
    if (!trimmedUserId) {
      alert('Please enter a User ID');
      return;
    }
    
    if (!trimmedOrganizationId) {
      alert('Please enter an Organization ID');
      return;
    }

    setValidating(true);
    try {
      // Get user info to fetch role
      try {
        const orgUsers = await axios.get(`${API_BASE_URL}/api/organizations/${trimmedOrganizationId}/users`);
        const user = orgUsers.data.find(u => u.user_id === trimmedUserId);
        setUserRole(user?.role || 'member');
      } catch (err) {
        setUserRole('member'); // Default if can't fetch
      }
      
      // Validate user by trying to get/create user
      // Note: Backend will create user with organization on first message
      await axios.get(`${API_BASE_URL}/api/user/${trimmedUserId}/chats/preview`);
      setValidatedUserId(trimmedUserId);
      setValidatedOrganizationId(trimmedOrganizationId);
      setValidatedTeamId(trimmedTeamId);
      setCurrentChatId(null);
      setMessages([]);
    } catch (error) {
      // If user doesn't exist, that's okay - we'll create on first message
      if (error.response && error.response.status === 404) {
        setValidatedUserId(trimmedUserId);
        setValidatedOrganizationId(trimmedOrganizationId);
        setValidatedTeamId(trimmedTeamId);
        setUserRole('member'); // Default role
        setCurrentChatId(null);
        setMessages([]);
        setUserChats([]);
      } else {
        alert('Error validating user ID. Please try again.');
        console.error('Error validating user:', error);
      }
    } finally {
      setValidating(false);
    }
  };

  const handleChatSelect = (chatId) => {
    setCurrentChatId(chatId);
    setMessages([]); // Clear messages, will load via useEffect
    setUploadedPdfs([]); // Clear PDFs, will load if needed
    setPdfUploadStatus(null); // Clear any status messages
    
    // Get sharing level for this chat
    const chat = userChats.find(c => c.chat_id === chatId);
    setCurrentChatSharingLevel(chat?.sharing_level || 'private');
  };

  const handleNewChat = () => {
    setCurrentChatId(null);
    setCurrentChatSharingLevel('private'); // Always default to private for new chat
    setMessages([]);
    setUploadedPdfs([]);
    setPdfUploadStatus(null);
  };
  
  // Set sharing level when starting a new chat (before first message)
  const handleSetSharingLevel = (isShared) => {
    if (!currentChatId) {
      // If no chat yet, set the level for the next chat
      setCurrentChatSharingLevel(isShared ? 'organization' : 'private');
    } else {
      // If chat exists, update it
      handleShareChat(isShared);
    }
  };

  const handleUserInputChange = (e) => {
    const selectedUserId = e.target.value;
    setUserId(selectedUserId);
    setShowUserSuggestions(true);
  };

  const handleResetUser = () => {
    setUserId('');
    setOrganizationId('');
    setTeamId('');
    setValidatedUserId('');
    setValidatedOrganizationId('');
    setValidatedTeamId('');
    setUserRole('');
    setCurrentChatId(null);
    setCurrentChatSharingLevel('private');
    setMessages([]);
    setUserChats([]);
    setUploadedPdfs([]);
    setPdfUploadStatus(null);
  };

  const handleStartChat = async () => {
    if (!validatedUserId) {
      alert('Please submit a User ID first');
      return;
    }
    
    // Create new chat by sending first message
    if (!currentChatId && inputMessage.trim()) {
      await sendMessage();
    }
  };

  const sendMessage = async () => {
    if (!inputMessage.trim() || !validatedUserId || !validatedOrganizationId) return;

    const userMessage = inputMessage.trim();
    setInputMessage('');
    setLoading(true);

    // Add user message to UI immediately
    const tempUserMessage = {
      message_id: `temp-${Date.now()}`,
      chat_id: currentChatId || 'pending',
      role: 'user',
      content: userMessage,
      created_at: new Date().toISOString()
    };
    setMessages(prev => [...prev, tempUserMessage]);

    try {
      const response = await axios.post(`${API_BASE_URL}/api/chat`, {
        user_id: validatedUserId,
        organization_id: validatedOrganizationId,
        team_id: validatedTeamId || null,
        chat_id: currentChatId,
        message: userMessage,
        pdf_document_id: pendingPdfDocumentId
        // Note: sharing_level is NOT sent here - it defaults to 'private' and only changes via toggle
      });

      // Set chat_id if this was a new chat
      if (!currentChatId) {
        setCurrentChatId(response.data.chat_id);
        // Clear uploaded PDFs list - they're now linked to the chat
        // Will reload when chat is selected or when we add an endpoint to fetch PDFs for a chat
        setUploadedPdfs([]);
        // Reload chats to show the new one (with sharing_level)
        setTimeout(() => loadUserChats(), 100);
      } else {
        // Reload chats to update the current chat
        setTimeout(() => loadUserChats(), 100);
      }

      // Replace temp message and add assistant response
      setMessages(prev => {
        const filtered = prev.filter(msg => msg.message_id !== tempUserMessage.message_id);
        return [
          ...filtered,
          {
            message_id: tempUserMessage.message_id,
            chat_id: response.data.chat_id,
            role: 'user',
            content: userMessage,
            created_at: new Date().toISOString(),
            has_pdf: response.data.has_pdf || false,
            pdf_document_id: response.data.pdf_document_id || null,
            pdf_filename: response.data.pdf_filename || null
          },
          {
            message_id: response.data.message_id,
            chat_id: response.data.chat_id,
            role: response.data.role,
            content: response.data.content,
            created_at: response.data.created_at,
            has_pdf: false, // Assistant doesn't have PDF
            pdf_document_id: null,
            pdf_filename: null
          }
        ];
      });
      
      // Clear pending PDF after sending
      if (pendingPdfDocumentId) {
        setPendingPdfDocumentId(null);
        // Remove from uploaded PDFs list since it's now attached to a message
        setUploadedPdfs(prev => prev.filter(pdf => pdf.document_id !== pendingPdfDocumentId));
      }
      
      // Always clear uploaded PDFs display after sending message - PDFs are now attached to messages
      // They'll show up as attachments in the message bubbles instead
      setUploadedPdfs([]);
    } catch (error) {
      console.error('Error sending message:', error);
      alert('Error sending message. Please try again.');
      // Remove temp message on error
      setMessages(prev => prev.filter(msg => msg.message_id !== tempUserMessage.message_id));
    } finally {
      setLoading(false);
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (currentChatId) {
        sendMessage();
      } else {
        handleStartChat();
      }
    }
  };

  const loadChatPdfs = async () => {
    if (!currentChatId || !validatedUserId) return;
    
    // Don't load PDFs that are already attached to messages
    // PDFs attached to messages will show up in message bubbles
    // Only show uploaded PDFs that haven't been sent yet (pending uploads)
    // Once a PDF is sent with a message, it's attached and shows in the message
    setUploadedPdfs([]);
    
    // Note: We used to load PDFs here, but now PDFs are attached to messages
    // so they display inline with messages (has_pdf flag), not in a separate section
  };

  const handlePdfUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    // Validate file type
    if (!file.type.includes('pdf') && !file.name.toLowerCase().endsWith('.pdf')) {
      setPdfUploadStatus({
        type: 'error',
        message: 'Please upload a PDF file (.pdf)'
      });
      return;
    }

    // Validate file size (10MB limit)
    const maxSize = 10 * 1024 * 1024; // 10MB
    if (file.size > maxSize) {
      setPdfUploadStatus({
        type: 'error',
        message: `File too large. Maximum size is 10MB (your file: ${(file.size / 1024 / 1024).toFixed(2)}MB)`
      });
      return;
    }

    // Ensure user and organization are validated
    if (!validatedUserId || !validatedOrganizationId) {
      setPdfUploadStatus({
        type: 'error',
        message: 'Please enter User ID and Organization ID first'
      });
      return;
    }

    // Create chat if doesn't exist
    let chatIdToUse = currentChatId;
    if (!chatIdToUse) {
      // For new chats, we'll create one by generating a temporary ID
      // The backend will handle chat creation properly
      chatIdToUse = null; // Let backend create it
    }

    setUploadingPdf(true);
    setPdfUploadStatus(null);

    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('user_id', validatedUserId);
      formData.append('organization_id', validatedOrganizationId);
      if (chatIdToUse) {
        formData.append('chat_id', chatIdToUse);
      }

      const response = await axios.post(
        `${API_BASE_URL}/api/pdf/upload`,
        formData,
        {
          headers: {
            'Content-Type': 'multipart/form-data',
          },
        }
      );

      // Update local state
      const newPdf = {
        document_id: response.data.document_id,
        filename: response.data.filename,
        num_chunks: response.data.num_chunks,
        uploaded_at: new Date().toISOString()
      };
      setUploadedPdfs(prev => [...prev, newPdf]);
      
      // Set PDF to attach to next message
      setPendingPdfDocumentId(response.data.document_id);

      // Note: Backend doesn't return chat_id in response, but creates chat on first message
      // If this was uploaded to a new chat, it will be linked when user sends first message

      // Reload chats to show updated list
      setTimeout(() => loadUserChats(), 500);

      setPdfUploadStatus({
        type: 'success',
        message: `PDF uploaded successfully! ${response.data.num_chunks} chunks indexed.`
      });

      // Reset file input
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }

    } catch (error) {
      console.error('Error uploading PDF:', error);
      const errorMessage = error.response?.data?.detail || error.message || 'Failed to upload PDF';
      setPdfUploadStatus({
        type: 'error',
        message: errorMessage
      });
    } finally {
      setUploadingPdf(false);
    }
  };

  const handlePdfButtonClick = () => {
    if (!validatedUserId || !validatedOrganizationId) {
      alert('Please enter User ID and Organization ID first');
      return;
    }
    fileInputRef.current?.click();
  };

  const handleShareChat = async (isShared) => {
    const chatId = currentChatId;
    if (!chatId || !validatedUserId) return;
    
    const sharingLevel = isShared ? 'organization' : 'private';
    
    try {
      // Note: In production, user_id should come from auth token
      const response = await axios.post(
        `${API_BASE_URL}/api/chats/${chatId}/share?user_id=${validatedUserId}`,
        { sharing_level: sharingLevel }
      );
      
      if (response.data.success) {
        setCurrentChatSharingLevel(sharingLevel);
        // Update chat in list
        setUserChats(prev => prev.map(chat => 
          chat.chat_id === chatId 
            ? { ...chat, sharing_level: sharingLevel }
            : chat
        ));
        // Reload chats to get updated sharing_level from backend
        setTimeout(() => loadUserChats(), 100);
      }
    } catch (error) {
      console.error('Error sharing chat:', error);
      const errorMsg = error.response?.data?.detail || 'Error sharing chat. Please try again.';
      alert(errorMsg);
    }
  };

  return (
    <div className="app">
      <div className="app-container">
        {/* Sidebar */}
        {validatedUserId && (
          <div className={`sidebar ${sidebarOpen ? 'open' : ''}`}>
            <div className="sidebar-header">
              <h2>Chats</h2>
              <button className="toggle-sidebar" onClick={() => setSidebarOpen(!sidebarOpen)}>
                {sidebarOpen ? '◀' : '▶'}
              </button>
            </div>
            <div className="sidebar-content">
              <div className="sidebar-user-info">
                <div className="user-id-display">
                  {userRole === 'team_lead' && <span className="lead-badge">(Lead)</span>}
                  {validatedTeamId && validatedTeamId !== 'Default' ? `${validatedTeamId} - ` : ''}
                  {validatedUserId}
                </div>
                <div className="organization-id-display">Organization: {validatedOrganizationId}</div>
                {validatedTeamId && (
                  <div className="team-id-display">Team: {validatedTeamId}</div>
                )}
                <button className="change-user-btn" onClick={handleResetUser}>
                  Change User
                </button>
              </div>
              <button className="new-chat-sidebar-btn" onClick={handleNewChat}>
                + New Chat
              </button>
              <div className="chat-list">
                {userChats.map((chat) => (
                  <div
                    key={chat.chat_id}
                    className={`chat-item ${currentChatId === chat.chat_id ? 'active' : ''}`}
                    onClick={() => handleChatSelect(chat.chat_id)}
                  >
                    <div className="chat-preview">
                      {chat.preview || 'Empty chat'}
                    </div>
                    <div className="chat-meta">
                      <span className="chat-date">
                        {new Date(chat.updated_at).toLocaleDateString()}
                      </span>
                      <span className={`chat-sharing-badge ${chat.sharing_level === 'organization' ? 'shared' : 'private'}`}>
                        {chat.sharing_level === 'organization' ? 'Public' : 'Private'}
                      </span>
                      <span className="chat-count">{chat.message_count} msgs</span>
                    </div>
                  </div>
                ))}
                {userChats.length === 0 && (
                  <div className="no-chats">No chats yet. Start a new conversation!</div>
                )}
              </div>
            </div>
          </div>
        )}

        <div className="chat-container">
          <div className="header">
            <div className="header-top">
              <div className="header-left">
                <h1>Memory Application</h1>
                <p className="enterprise-badge">Enterprise Edition</p>
              </div>
            </div>
            {!validatedUserId && (
              <form className="user-selector" onSubmit={handleUserSubmit}>
              <div className="registration-fields">
                <div className="field-group">
                  <label htmlFor="organizationId">Organization:</label>
                  <div className="autocomplete-wrapper">
                    <input
                      id="organizationId"
                      type="text"
                      value={organizationId}
                      onChange={(e) => {
                        setOrganizationId(e.target.value);
                        setShowOrgSuggestions(true);
                      }}
                      onFocus={() => setShowOrgSuggestions(true)}
                      onBlur={() => setTimeout(() => setShowOrgSuggestions(false), 200)}
                      placeholder="Enter or select Organization"
                      disabled={!!validatedUserId || validating}
                    />
                    {showOrgSuggestions && organizations.length > 0 && (
                      <div className="autocomplete-dropdown">
                        {organizations
                          .filter(org => 
                            org.organization_id.toLowerCase().includes(organizationId.toLowerCase()) ||
                            org.organization_name.toLowerCase().includes(organizationId.toLowerCase())
                          )
                          .map(org => (
                            <div
                              key={org.organization_id}
                              className="autocomplete-item"
                              onClick={() => {
                                setOrganizationId(org.organization_id);
                                setShowOrgSuggestions(false);
                              }}
                            >
                              <strong>{org.organization_name}</strong>
                              <span className="autocomplete-id">({org.organization_id})</span>
                            </div>
                          ))}
                        {organizationId.trim() && !organizations.some(org => 
                          org.organization_id.toLowerCase() === organizationId.toLowerCase()
                        ) && (
                          <div className="autocomplete-item create-new">
                            <span>Create new: "{organizationId}"</span>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
                
                {organizationId.trim() && (
                  <>
                    <div className="field-group">
                      <label htmlFor="teamId">Team (Optional):</label>
                      <div className="autocomplete-wrapper">
                        <input
                          id="teamId"
                          type="text"
                          value={teamId}
                          onChange={(e) => {
                            setTeamId(e.target.value);
                            setShowTeamSuggestions(true);
                          }}
                          onFocus={() => setShowTeamSuggestions(true)}
                          onBlur={() => setTimeout(() => setShowTeamSuggestions(false), 200)}
                          placeholder="Enter or select Team"
                          disabled={!!validatedUserId || validating}
                        />
                        {showTeamSuggestions && organizationTeams.length > 0 && (
                          <div className="autocomplete-dropdown">
                            {organizationTeams
                              .filter(team => 
                                team.team_id.toLowerCase().includes(teamId.toLowerCase()) ||
                                team.team_name.toLowerCase().includes(teamId.toLowerCase())
                              )
                              .map(team => (
                                <div
                                  key={team.team_id}
                                  className="autocomplete-item"
                                  onClick={() => {
                                    setTeamId(team.team_id);
                                    setShowTeamSuggestions(false);
                                  }}
                                >
                                  <strong>{team.team_name}</strong>
                                  <span className="autocomplete-id">({team.team_id})</span>
                                </div>
                              ))}
                            {teamId.trim() && !organizationTeams.some(team => 
                              team.team_id.toLowerCase() === teamId.toLowerCase()
                            ) && (
                              <div className="autocomplete-item create-new">
                                <span>Create new: "{teamId}"</span>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                    
                    <div className="field-group">
                      <label htmlFor="userId">User:</label>
                      <div className="autocomplete-wrapper">
                        <input
                          id="userId"
                          type="text"
                          value={userId}
                          onChange={(e) => {
                            setUserId(e.target.value);
                            setShowUserSuggestions(true);
                          }}
                          onFocus={() => setShowUserSuggestions(true)}
                          onBlur={() => setTimeout(() => setShowUserSuggestions(false), 200)}
                          placeholder="Enter or select User ID"
                          disabled={!!validatedUserId || validating}
                        />
                        {showUserSuggestions && organizationUsers.length > 0 && (
                          <div className="autocomplete-dropdown">
                            {organizationUsers
                              .filter(user => 
                                user.user_id.toLowerCase().includes(userId.toLowerCase())
                              )
                              .map(user => (
                                <div
                                  key={user.user_id}
                                  className="autocomplete-item"
                                  onClick={() => {
                                    setUserId(user.user_id);
                                    setShowUserSuggestions(false);
                                  }}
                                >
                                  <strong>{user.user_id}</strong>
                                  <span className="autocomplete-role">{user.role}</span>
                                </div>
                              ))}
                            {userId.trim() && !organizationUsers.some(user => 
                              user.user_id.toLowerCase() === userId.toLowerCase()
                            ) && (
                              <div className="autocomplete-item create-new">
                                <span>Create new: "{userId}"</span>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  </>
                )}
              </div>
              {!validatedUserId ? (
                <button 
                  type="submit" 
                  className="submit-user-btn"
                  disabled={!userId.trim() || !organizationId.trim() || validating}
                >
                  {validating ? 'Validating...' : 'Register & Start'}
                </button>
              ) : (
                <div className="validated-user-info">
                  <div className="validated-info-display">
                    <span className="validated-user-id">✓ User: {validatedUserId}</span>
                    <span className="validated-organization-id">✓ Organization: {validatedOrganizationId}</span>
                    {validatedTeamId && (
                      <span className="validated-team-id">✓ Team: {validatedTeamId}</span>
                    )}
                  </div>
                  <button 
                    type="button"
                    className="reset-user-btn"
                    onClick={handleResetUser}
                  >
                    Change
                  </button>
                </div>
              )}
            </form>
            )}
            
            {/* Chat-specific header with share toggle - only when chat is active */}
            {currentChatId && validatedUserId && (
              <div className="chat-header-bar">
                <div className="chat-header-left">
                  <span className="chat-title">Chat</span>
                </div>
                <div className="chat-header-right">
                  <div className="share-toggle-container">
                    <label className="share-toggle-label">
                      <span className="share-toggle-text">
                        {currentChatSharingLevel === 'organization' ? 'Shared' : 'Private'}
                      </span>
                      <input
                        type="checkbox"
                        checked={currentChatSharingLevel === 'organization'}
                        onChange={(e) => handleShareChat(e.target.checked)}
                        className="share-toggle-switch"
                      />
                      <span className="share-toggle-slider"></span>
                    </label>
                  </div>
                </div>
              </div>
            )}
          </div>

        <div className="messages-container">
          {messages.length === 0 && !uploadingPdf && (
            <div className="empty-state">
              <div className="empty-state-content">
                <div className="empty-state-icon">💬</div>
                <p>Start a conversation by typing a message below</p>
                <p className="empty-state-hint">
                  Or upload a PDF document to ask questions about it
                </p>
              </div>
            </div>
          )}
          {messages.map((message) => (
            <div
              key={message.message_id}
              className={`message ${message.role === 'user' ? 'user-message' : 'assistant-message'}`}
            >
              <div className="message-content">
                <div className="message-role">
                  {message.role === 'user' ? 'You' : 'AI'}
                  {message.has_pdf && message.role === 'user' && (
                    <span className="pdf-attachment-icon" title={message.pdf_filename || 'PDF attached'}>
                      📄
                    </span>
                  )}
                </div>
                <div className="message-text">{message.content}</div>
                {message.has_pdf && message.pdf_filename && (
                  <div className="pdf-attachment-label">
                    <span className="pdf-icon-small">📄</span>
                    <span className="pdf-filename-text">{message.pdf_filename}</span>
                  </div>
                )}
              </div>
            </div>
          ))}
          {loading && (
            <div className="message assistant-message">
              <div className="message-content">
                <div className="message-role">AI</div>
                <div className="message-text typing-indicator">
                  <span></span>
                  <span></span>
                  <span></span>
                </div>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* PDF Upload Status Message */}
        {pdfUploadStatus && (
          <div className={`pdf-status-message ${pdfUploadStatus.type}`}>
            <span className="pdf-status-icon">
              {pdfUploadStatus.type === 'success' ? '✓' : '✗'}
            </span>
            <span className="pdf-status-text">{pdfUploadStatus.message}</span>
          </div>
        )}

        {/* Uploaded PDFs Display */}
        {uploadedPdfs.length > 0 && (
          <div className="uploaded-pdfs-container">
            <div className="uploaded-pdfs-header">
              <span className="pdf-icon">📄</span>
              <span className="uploaded-pdfs-title">Uploaded Documents</span>
            </div>
            <div className="uploaded-pdfs-list">
              {uploadedPdfs.map((pdf) => (
                <div key={pdf.document_id} className="uploaded-pdf-item">
                  <span className="pdf-filename">{pdf.filename}</span>
                  <span className="pdf-meta">{pdf.num_chunks} chunks</span>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="input-container">
          {/* Hidden file input */}
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,application/pdf"
            onChange={handlePdfUpload}
            style={{ display: 'none' }}
            disabled={!validatedUserId || uploadingPdf}
          />
          
          {/* PDF Upload Button */}
          <button
            onClick={handlePdfButtonClick}
            disabled={!validatedUserId || uploadingPdf || loading}
            className="pdf-upload-button"
            title="Upload PDF document"
          >
            {uploadingPdf ? (
              <span className="upload-spinner">⏳</span>
            ) : (
              <span className="pdf-icon">📄</span>
            )}
            <span className="pdf-button-text">{uploadingPdf ? 'Uploading...' : 'Upload PDF'}</span>
          </button>
          <textarea
            value={inputMessage}
            onChange={(e) => setInputMessage(e.target.value)}
            onKeyPress={handleKeyPress}
            placeholder={currentChatId ? "Type your message..." : "Type a message to start chat..."}
            rows={3}
            disabled={!validatedUserId || loading || uploadingPdf}
          />
          <button
            onClick={currentChatId ? sendMessage : handleStartChat}
            disabled={!validatedUserId || !inputMessage.trim() || loading || uploadingPdf}
            className="send-button"
          >
            {loading ? 'Sending...' : 'Send'}
          </button>
        </div>
        </div>
      </div>
    </div>
  );
}

export default App;

