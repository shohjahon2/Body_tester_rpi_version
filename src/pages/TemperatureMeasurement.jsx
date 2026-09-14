import React, { useState, useEffect } from 'react'; // Добавили useEffect
import { useNavigate } from 'react-router-dom';
import Button from '../components/Button';
import '../styles/pages/_temperature-measurement.scss';

const TemperatureMeasurement = () => {
  const navigate = useNavigate();
  const [temperature, setTemperature] = useState('');

  // --- ИНТЕГРАЦИЯ С BACKEND ---
  useEffect(() => {
    // Функция для получения данных с Raspberry Pi
    const fetchTemperature = async () => {
      try {
        // Замени localhost на IP адрес твоей Raspberry, если заходишь с другого устройства
        const response = await fetch('http://localhost:8000/temperature');
        const data = await response.json();
        
        if (data.temperature && data.temperature > 0) {
          // Если датчик выдает температуру (например, > 30°C), фиксируем её
          setTemperature(data.temperature.toString());
        }
      } catch (error) {
        console.error("Ошибка подключения к датчику:", error);
      }
    };

    // Запускаем опрос каждые 1000 мс (1 секунда)
    const interval = setInterval(fetchTemperature, 1000);

    // Очистка интервала при закрытии страницы
    return () => clearInterval(interval);
  }, []);
  // --- КОНЕЦ ИНТЕГРАЦИИ ---

  const handleTemperatureChange = (e) => {
    const value = e.target.value;
    if (value === '' || /^\d*\.?\d*$/.test(value)) {
      setTemperature(value);
    }
  };

  const handleFinish = () => {
    localStorage.setItem('temperature', temperature);
    const isAllMeasurementsMode = localStorage.getItem('isAllMeasurementsMode') === 'true';
    
    if (isAllMeasurementsMode) {
      const measurementQueue = JSON.parse(localStorage.getItem('measurementQueue') || '[]');
      const currentIndex = parseInt(localStorage.getItem('currentMeasurementIndex') || '0');
      const nextIndex = currentIndex + 1;
      
      if (nextIndex < measurementQueue.length) {
        localStorage.setItem('currentMeasurementIndex', nextIndex.toString());
        const nextMeasurement = measurementQueue[nextIndex];
        navigate(`/measurement/${nextMeasurement}`);
      } else {
        localStorage.removeItem('measurementQueue');
        localStorage.removeItem('currentMeasurementIndex');
        localStorage.removeItem('isAllMeasurementsMode');
        navigate('/success');
      }
    } else {
      navigate('/success');
    }
  };

  const hasTemperature = temperature !== '' && parseFloat(temperature) > 0;

  return (
    <div className="temperature-measurement">
      <div className="temperature-measurement__container">
        <div className="temperature-measurement__content">
          <div className="temperature-measurement__instructions">
            <p className="temperature-measurement__text">
              Iltimos tana haroratingizni o'lchash uchun ko'rsatilgan joyga peshonangizni tuting
            </p>
          </div>

          <div className="temperature-measurement__display">
            <div className="temperature-measurement__display-box">
              <h3 className="temperature-measurement__display-title">Tana harorati</h3>
              <div className="temperature-measurement__display-content">
                <img 
                  src="/assets/icons/temperature_b.svg" 
                  alt="Temperature" 
                  className="temperature-measurement__display-icon"
                />
                <input
                  type="text"
                  className="temperature-measurement__display-value"
                  value={temperature}
                  onChange={handleTemperatureChange}
                  placeholder="--"
                  inputMode="decimal"
                />
                <span className="temperature-measurement__display-unit">°C</span>
              </div>
            </div>
          </div>

          <div className="temperature-measurement__illustration">
            <img 
              src="/assets/imgs/temperature.webp" 
              alt="Temperature measurement" 
              className="temperature-measurement__image"
            />
          </div>

          {hasTemperature && (
            <div className="temperature-measurement__button-wrapper">
              <Button 
                onClick={handleFinish} 
                className="temperature-measurement__button"
              >
                Tugatish
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default TemperatureMeasurement;