import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import Button from '../components/Button';
import '../styles/pages/_oxygen-measurement.scss';

const OxygenMeasurement = () => {
  const navigate = useNavigate();
  const [oxygen, setOxygen] = useState('');
  const [error, setError] = useState(null);
  const [isReading, setIsReading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [isCompleted, setIsCompleted] = useState(false);
  
  const isComponentMounted = useRef(true);
  const intervalRef = useRef(null);

  const fetchOxygenData = async () => {
    if (isCompleted) return; 
    
    try {
      setIsReading(true);
      // Добавляем timestamp чтобы избежать кэширования запроса
      const response = await fetch(`http://127.0.0.1:8000/oxygen?t=${Date.now()}`);
      const data = await response.json();
  
      if (isComponentMounted.current) {
        setProgress(data.progress || 0);
  
        // Если статус "completed" - фиксируем всё
        if (data.status === 'completed') {
          setIsCompleted(true);
          setOxygen(data.oxygen); // Здесь появится финальное число
          setError(null);
          if (intervalRef.current) clearInterval(intervalRef.current);
        } 
        // Если идет процесс измерения
        else if (data.status === 'measuring') {
          setError(null);
          setOxygen('--'); // Пока идет замер, всегда показываем прочерки
        } 
        // Если палец не найден
        else if (data.status === 'waiting') {
          setOxygen('--');
          setProgress(0);
          setError("Barmog'ingizni sensorga qo'ying");
        }
      }
    } catch (err) {
      if (isComponentMounted.current) setError("Server bilan aloqa yo'q");
    } finally {
      if (isComponentMounted.current) setIsReading(false);
    }
  };


  useEffect(() => {
    isComponentMounted.current = true;

    // --- ГЛАВНОЕ ИСПРАВЛЕНИЕ: Сброс при загрузке страницы ---
    const resetOnStart = async () => {
      try {
        await fetch('http://127.0.0.1:8000/oxygen/reset', { method: 'POST' });
      } catch (e) {
        console.error("Reset failed", e);
      }
    };

    resetOnStart().then(() => {
      if (isComponentMounted.current) {
        fetchOxygenData();
        intervalRef.current = setInterval(fetchOxygenData, 500);
      }
    });

    return () => {
      isComponentMounted.current = false;
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, []);

  const handleFinish = () => {
    if (!isCompleted) return;
    localStorage.setItem('oxygen', oxygen);
    
    const isAllMeasurementsMode = localStorage.getItem('isAllMeasurementsMode') === 'true';
    if (isAllMeasurementsMode) {
      const measurementQueue = JSON.parse(localStorage.getItem('measurementQueue') || '[]');
      const currentIndex = parseInt(localStorage.getItem('currentMeasurementIndex') || '0');
      const nextIndex = currentIndex + 1;
      
      if (nextIndex < measurementQueue.length) {
        localStorage.setItem('currentMeasurementIndex', nextIndex.toString());
        navigate(`/measurement/${measurementQueue[nextIndex]}`);
      } else {
        clearMeasurementStates();
        navigate('/success');
      }
    } else {
      navigate('/success');
    }
  };

  const clearMeasurementStates = () => {
    localStorage.removeItem('measurementQueue');
    localStorage.removeItem('currentMeasurementIndex');
    localStorage.removeItem('isAllMeasurementsMode');
  };

  return (
    <div className="oxygen-measurement">
      <div className="oxygen-measurement__container">
        <div className="oxygen-measurement__content">
          <div className="oxygen-measurement__instructions">
            <p className="oxygen-measurement__text">
              {error ? (
                <span className="error-msg" style={{ color: '#ff4d4f', fontWeight: 'bold' }}>
                  {error}
                </span>
              ) : isCompleted ? (
                <span style={{ color: '#4CAF50', fontWeight: 'bold' }}>O'lchash yakunlandi!</span>
              ) : (
                `Jarayon: ${progress * 10}%`
              )}
            </p>
          </div>

          <div className="oxygen-measurement__display">
            <div className={`oxygen-measurement__display-box ${isReading && !isCompleted ? 'loading' : ''} ${isCompleted ? 'completed' : ''}`}>
              <h3 className="oxygen-measurement__display-title">Kislorod miqdori</h3>
              <div className="oxygen-measurement__display-content">
                <img 
                  src="/assets/icons/amountOfOxyghen.svg" 
                  alt="Oxygen" 
                  className={`oxygen-measurement__display-icon ${isReading && !isCompleted ? 'pulse' : ''}`}
                />
                <div className="oxygen-measurement__display-value">
                  {oxygen || '--'}
                </div>
                <span className="oxygen-measurement__display-unit">%</span>
              </div>
              
              {/* Полоска прогресса */}
              <div className="progress-container" style={{ width: '100%', height: '8px', background: '#eee', marginTop: '15px', borderRadius: '4px', overflow: 'hidden' }}>
                <div style={{ 
                  width: `${progress * 10}%`, 
                  height: '100%', 
                  background: isCompleted ? '#4CAF50' : '#2196F3', 
                  transition: 'width 0.4s ease-out' 
                }} />
              </div>
            </div>
          </div>

          <div className="oxygen-measurement__illustration">
            <img 
              src="/assets/imgs/blood_test_finger.webp" 
              alt="Blood oxygen" 
              className="oxygen-measurement__image" 
            />
          </div>

          {isCompleted && (
            <div className="oxygen-measurement__button-wrapper">
              <Button onClick={handleFinish} className="oxygen-measurement__button">
                Tugatish
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default OxygenMeasurement;