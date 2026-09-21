import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import '../styles/pages/_selection.scss';

const Selection = () => {
  const navigate = useNavigate();
  const [selectedCards, setSelectedCards] = useState([]);

  const cards = [
    {
      id: 'weight-height',
      title: "Tana vazni va bo'yni o'lchash",
      icon: '/assets/icons/weight_w.svg',
      icon2: '/assets/icons/height_w.svg',
      color: '#00A0A0',
      borderColor: '#007BFF',
      route: '/measurement/weight-height'
    },
    {
      id: 'temperature',
      title: "Tana haroratini o'lchash",
      icon: '/assets/icons/temperature_w.svg',
      color: '#8A2BE2',
      route: '/measurement/temperature'
    },
    {
      id: 'oxygen',
      title: "Qondagi kislorod miqdorini o'lchash",
      icon: '/assets/icons/bloodOxyghn_w.svg',
      color: '#A00000',
      route: '/measurement/oxygen'
    },
    {
      id: 'blood-pressure',
      title: "Qon bosimi va pulsni o'lchash",
      icon: '/assets/icons/bloodPressure_w.svg',
      color: '#E00000',
      route: '/measurement/blood-pressure'
    }
  ];

  const handleCardClick = (card) => {
    // Alohida bo'lim tanlanmoqda — oldingi "Hammasini tanlash" seansidan
    // qolib ketgan navbatni tozalash kerak, aks holda GenderSelection
    // shu eski navbatning joriy bosqichiga (masalan oxygenga) olib ketaveradi.
    localStorage.removeItem('measurementQueue');
    localStorage.removeItem('currentMeasurementIndex');
    localStorage.removeItem('isAllMeasurementsMode');

    // Store selected measurement type and navigate to gender selection
    localStorage.setItem('selectedMeasurement', card.id);
    navigate('/gender-selection');
  };

  const handleSelectAll = () => {
    if (selectedCards.length === cards.length) {
      setSelectedCards([]);
      // Clear all measurements mode
      localStorage.removeItem('measurementQueue');
      localStorage.removeItem('currentMeasurementIndex');
      localStorage.removeItem('isAllMeasurementsMode');
    } else {
      setSelectedCards(cards.map(card => card.id));
      // Set up for all measurements flow
      const measurementOrder = ['weight-height', 'temperature', 'oxygen', 'blood-pressure'];
      localStorage.setItem('measurementQueue', JSON.stringify(measurementOrder));
      localStorage.setItem('currentMeasurementIndex', '0');
      localStorage.setItem('isAllMeasurementsMode', 'true');
      // Navigate to gender selection first
      navigate('/gender-selection');
    }
  };

  const handleCardDoubleClick = (card) => {
    navigate(card.route);
  };

  return (
    <div className="selection">
      <div className="selection__container">
        <div className="selection__content">
          <h2 className="selection__title">O'zingizga kerakli bo'lgan bo'limni tanlang</h2>

          <div className="selection__grid">
            {cards.map((card) => (
              <div
                key={card.id}
                className={`selection__card ${selectedCards.includes(card.id) ? 'selection__card--selected' : ''}`}
                onClick={() => handleCardClick(card)}
                onDoubleClick={() => handleCardDoubleClick(card)}
                style={{
                  backgroundColor: card.color,
                  borderColor: selectedCards.includes(card.id) ? card.borderColor || card.color : 'transparent',
                  ['--hover-border-color']: card.borderColor || card.color
                }}
              >
                <div className="selection__card-icons">
                  <img
                    src={card.icon}
                    alt={card.title}
                    className="selection__card-icon"
                  />
                  {card.icon2 && (
                    <img
                      src={card.icon2}
                      alt=""
                      className="selection__card-icon"
                    />
                  )}
                </div>
                <p className="selection__card-text">{card.title}</p>
              </div>
            ))}
          </div>

          <div className="selection__button-wrapper">
            <button
              className="selection__select-all"
              onClick={handleSelectAll}
            >
              Hammasini tanlash
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Selection;
