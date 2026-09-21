import React, { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import * as faceapi from 'face-api.js';
import { FaUser, FaTimes } from 'react-icons/fa';
import Button from '../components/Button';
import '../styles/pages/_registration.scss';

// Lokal (brauzerda, tarmoqqa so'rovsiz) yuz bor-yo'qligini tekshirish
// tezligi. Yengil model — Pi'da ham har 300ms da bemalol ishlaydi.
const LOCAL_DETECT_INTERVAL_MS = 300;
// Yuz doim kadrda tursa ham backendga (og'ir InsightFace) shuncha
// oraliqdan tez-tez so'rov yubormaymiz.
const BACKEND_CALL_MIN_GAP_MS = 1000;
const DETECT_OPTIONS = new faceapi.TinyFaceDetectorOptions({ inputSize: 224, scoreThreshold: 0.5 });

// Yuz "to'g'ri" turibdimi — hujjat: "Past sifatli kadrni yubormang".
// Juda kichik (uzoqda) yoki chekkada (chala) tursa backendga umuman
// yubormaymiz — vaqtincha kutamiz, odamga ekranda yo'l-yo'riq beramiz.
const MIN_FACE_WIDTH_RATIO = 0.15;   // kadr kengligining kamida 15% i
const CENTER_X_RANGE = [0.2, 0.8];   // markaz gorizontal chegarasi
const CENTER_Y_RANGE = [0.1, 0.9];   // markaz vertikal chegarasi
// To'g'ri joylashgan kadr ketma-ket shuncha marta tasdiqlangandan
// keyingina yuboriladi — o'tayotgan/tebranayotgan yuzni ushlab
// qolmaslik uchun (tarozi/bo'y sensoridagi barqarorlik tekshiruviga
// o'xshash g'oya).
const STABLE_FRAMES_REQUIRED = 2;

// Taniqli bemor topilganda darhol o'tib ketmasdan, shuncha soniya
// ekranda "bu sizmisiz?" deb ko'rsatiladi — xato moslik bo'lsa, odam
// "Yo'q, men emasman" deb bekor qila oladi. Hech narsa bosmasa,
// muddat tugagach o'zi davom etadi (tez yo'l saqlanadi).
const CONFIRM_TIMEOUT_MS = 6000;

function frameQuality(box, videoWidth, videoHeight) {
  const widthRatio = box.width / videoWidth;
  const centerX = (box.x + box.width / 2) / videoWidth;
  const centerY = (box.y + box.height / 2) / videoHeight;

  if (widthRatio < MIN_FACE_WIDTH_RATIO) {
    return { ok: false, hint: 'Kameraga yaqinroq keling' };
  }
  if (centerX < CENTER_X_RANGE[0] || centerX > CENTER_X_RANGE[1]
    || centerY < CENTER_Y_RANGE[0] || centerY > CENTER_Y_RANGE[1]) {
    return { ok: false, hint: 'Yuzingizni markazga joylashtiring' };
  }
  return { ok: true, hint: '' };
}

const Registration = () => {
  const navigate = useNavigate();
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const busyRef = useRef(false);
  const detectingRef = useRef(false);
  const lastCallRef = useRef(0);
  const goodStreakRef = useRef(0);
  const [stream, setStream] = useState(null);
  const [photo, setPhoto] = useState(null);
  const [name, setName] = useState('');
  const [isGuest, setIsGuest] = useState(false);
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const [modelsLoaded, setModelsLoaded] = useState(false);
  const [modelsFailed, setModelsFailed] = useState(false);
  const [confirmResult, setConfirmResult] = useState(null);
  const [confirmSecondsLeft, setConfirmSecondsLeft] = useState(0);

  useEffect(() => {
    // Start camera when component mounts (if not guest mode)
    if (!isGuest) {
      startCamera();
    }

    return () => {
      // Cleanup: stop camera when component unmounts
      stopCamera();
    };
  }, [isGuest]);

  // Yuz aniqlash modelini bir marta yuklaymiz — brauzerda ishlaydi,
  // internetga/backendga hech qanday so'rov ketmaydi.
  useEffect(() => {
    let cancelled = false;
    faceapi.nets.tinyFaceDetector
      .loadFromUri('/models')
      .then(() => {
        if (!cancelled) setModelsLoaded(true);
      })
      .catch((err) => {
        console.error('Yuz aniqlash modelini yuklab bo\'lmadi, zaxira usulga o\'tildi:', err);
        if (!cancelled) setModelsFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Knopkasiz doimiy skanerlash: kadr faqat KAMERADA HAQIQATDA YUZ
  // ko'ringandagina backendga yuboriladi — bo'sh kadrni "ahmoqona"
  // muntazam yuborish yo'q. Yuz borligini o'zi (TinyFaceDetector)
  // tekshiradi; backend faqat tanishning og'ir (InsightFace) qismini
  // bajaradi.
  useEffect(() => {
    if (isGuest || photo || confirmResult || !stream) return undefined;
    if (!modelsLoaded && !modelsFailed) return undefined;

    const timer = setInterval(async () => {
      if (busyRef.current || detectingRef.current) return;

      if (!modelsLoaded) {
        // Model yuklanmagan — zaxira: oldingidek oraliq bilan yuboraveramiz.
        const now = Date.now();
        if (now - lastCallRef.current >= BACKEND_CALL_MIN_GAP_MS) {
          lastCallRef.current = now;
          scanFrame();
        }
        return;
      }

      const video = videoRef.current;
      if (!video || video.readyState < 2) return;

      detectingRef.current = true;
      try {
        const detection = await faceapi.detectSingleFace(video, DETECT_OPTIONS);
        if (!detection) {
          goodStreakRef.current = 0;
          setStatus('');
          return;
        }

        const quality = frameQuality(detection.box, video.videoWidth, video.videoHeight);
        if (!quality.ok) {
          goodStreakRef.current = 0;
          setStatus(quality.hint);
          return;
        }

        goodStreakRef.current += 1;
        if (goodStreakRef.current < STABLE_FRAMES_REQUIRED) {
          setStatus('Aniqlanmoqda...');
          return;
        }

        const now = Date.now();
        if (now - lastCallRef.current >= BACKEND_CALL_MIN_GAP_MS) {
          lastCallRef.current = now;
          scanFrame();
        }
      } catch (err) {
        console.warn('Lokal yuz aniqlashda xato:', err);
      } finally {
        detectingRef.current = false;
      }
    }, LOCAL_DETECT_INTERVAL_MS);

    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isGuest, photo, confirmResult, stream, modelsLoaded, modelsFailed]);

  // "Bu sizmisiz?" tasdiqlash oynasi — muddat tugagach o'zi davom etadi.
  useEffect(() => {
    if (!confirmResult) return undefined;

    setConfirmSecondsLeft(Math.ceil(CONFIRM_TIMEOUT_MS / 1000));
    const tickTimer = setInterval(() => {
      setConfirmSecondsLeft((s) => Math.max(0, s - 1));
    }, 1000);
    const goTimer = setTimeout(() => {
      goToNextStep(confirmResult);
      setConfirmResult(null);
    }, CONFIRM_TIMEOUT_MS);

    return () => {
      clearInterval(tickTimer);
      clearTimeout(goTimer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [confirmResult]);

  const startCamera = async () => {
    try {
      const mediaStream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'user' }
      });
      setStream(mediaStream);
      if (videoRef.current) {
        videoRef.current.srcObject = mediaStream;
      }
      setError('');
    } catch (err) {
      setError('Kameraga kirish imkoni yo\'q. Iltimos, ruxsat bering.');
      console.error('Error accessing camera:', err);
    }
  };

  const stopCamera = () => {
    if (stream) {
      stream.getTracks().forEach(track => track.stop());
      setStream(null);
    }
  };

  const grabFrame = () => {
    if (!videoRef.current || !canvasRef.current) return null;
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video.videoWidth) return null;
    const context = canvas.getContext('2d');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL('image/jpeg', 0.85);
  };

  const goToNextStep = (result) => {
    localStorage.setItem('userData', JSON.stringify({
      isGuest: false,
      name: result.name || '',
      photo: null,
    }));
    localStorage.setItem('patientId', String(result.patient_id));
    localStorage.removeItem('pendingEmbedding');
    stopCamera();
    navigate('/home');
  };

  const scanFrame = () => {
    const frameData = grabFrame();
    if (!frameData) return;

    busyRef.current = true;
    fetch('http://localhost:8000/face/identify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ photo: frameData, name: name.trim() || 'guest' }),
    })
      .then(res => res.json())
      .then(result => {
        if (result.status === 'found') {
          // Bemor topildi — lekin darhol o'tib ketmasdan, avval "bu
          // sizmisiz?" deb tasdiqlash so'raladi (xato moslik bo'lsa
          // bekor qilish imkoni bo'lsin).
          setStatus('');
          setConfirmResult(result);
        } else if (result.status === 'not_found') {
          // Yangi odam — kadr saqlanadi, ism kiritish uchun to'xtaymiz.
          setPhoto(frameData);
          setStatus('');
          stopCamera();
          localStorage.setItem('pendingEmbedding', JSON.stringify({
            embedding: result.embedding,
            quality_score: result.quality_score,
          }));
          localStorage.removeItem('patientId');
        } else if (result.status === 'no_face') {
          setStatus('');
        } else {
          // ambiguous / error / not_configured — skanerlashni davom
          // ettiramiz, avtomatik yangi bemor yaratmaymiz.
          console.warn('Yuz tanish natijasi:', result.status, result.detail || '');
          setStatus('');
        }
      })
      .catch(err => {
        console.warn('Yuz tanishga ulanib bo\'lmadi:', err);
        setStatus('');
      })
      .finally(() => {
        busyRef.current = false;
      });
  };

  const confirmYes = () => {
    if (!confirmResult) return;
    goToNextStep(confirmResult);
    setConfirmResult(null);
  };

  const confirmNo = () => {
    // Noto'g'ri moslik — bekor qilib, qaytadan skanerlashni davom
    // ettiramiz. Hech narsa saqlanmagan edi (localStorage'ga hali
    // yozilmagan), shuning uchun tozalash shart emas.
    setConfirmResult(null);
    setStatus('');
    goodStreakRef.current = 0;
  };

  const retakePhoto = () => {
    setPhoto(null);
    setStatus('');
    goodStreakRef.current = 0;
    startCamera();
  };

  const handleContinue = () => {
    if (isGuest) {
      // Guest mode - save guest info
      localStorage.setItem('userData', JSON.stringify({
        isGuest: true,
        name: 'Mehmon',
        photo: null
      }));
      navigate('/home');
    } else {
      // Registration mode - check if photo and name are provided
      if (!photo) {
        setError('Iltimos, yuzingizni kameraga ko\'rsating');
        return;
      }
      if (!name.trim()) {
        setError('Iltimos, ismingizni kiriting');
        return;
      }

      // Save registration data
      localStorage.setItem('userData', JSON.stringify({
        isGuest: false,
        name: name.trim(),
        photo: photo
      }));

      navigate('/home');
    }
  };

  const handleGuestMode = () => {
    setIsGuest(true);
    stopCamera();
    setError('');
  };

  const handleRegisterMode = () => {
    setIsGuest(false);
    setPhoto(null);
    setName('');
    startCamera();
  };

  return (
    <div className="registration">
      <div className="registration__container">
        <div className="registration__content">
          <h2 className="registration__title">Ro'yxatdan o'tish</h2>

          {!isGuest ? (
            <>
              {confirmResult ? (
                <div className="registration__confirm">
                  <div className="registration__confirm-icon">
                    <FaUser />
                  </div>
                  <p className="registration__confirm-title">Bu sizmisiz?</p>
                  <p className="registration__confirm-name">
                    {confirmResult.name || `Bemor #${confirmResult.patient_id}`}
                  </p>
                  <div className="registration__confirm-buttons">
                    <button
                      className="registration__confirm-button registration__confirm-button--no"
                      onClick={confirmNo}
                    >
                      Yo'q, men emasman
                    </button>
                    <button
                      className="registration__confirm-button registration__confirm-button--yes"
                      onClick={confirmYes}
                    >
                      Ha, bu men ({confirmSecondsLeft})
                    </button>
                  </div>
                </div>
              ) : (
                <div className="registration__camera-section">
                  {!photo ? (
                    <div className="registration__video-wrapper">
                      <video
                        ref={videoRef}
                        autoPlay
                        playsInline
                        className="registration__video"
                      />
                      <div className="registration__camera-overlay">
                        <div className="registration__camera-frame"></div>
                      </div>
                    </div>
                  ) : (
                    <div className="registration__photo-wrapper">
                      <img
                        src={photo}
                        alt="Captured"
                        className="registration__photo"
                      />
                      <button
                        className="registration__retake-button"
                        onClick={retakePhoto}
                        aria-label="Retake photo"
                      >
                        <FaTimes />
                      </button>
                    </div>
                  )}
                </div>
              )}

              {!photo && !confirmResult && (
                <p className="registration__hint">
                  {status || (!modelsLoaded && !modelsFailed
                    ? 'Tayyorlanmoqda...'
                    : 'Yuzingizni kameraga ko\'rsating — avtomatik aniqlanadi')}
                </p>
              )}

              {photo && (
                <div className="registration__name-section">
                  <div className="registration__name-input-wrapper">
                    <FaUser className="registration__name-icon" />
                    <input
                      type="text"
                      className="registration__name-input"
                      placeholder="Ismingizni kiriting"
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      maxLength={50}
                    />
                  </div>
                </div>
              )}
            </>
          ) : (
            <div className="registration__guest-section">
              <div className="registration__guest-icon">
                <FaUser />
              </div>
              <p className="registration__guest-text">
                Mehmon sifatida davom etish
              </p>
            </div>
          )}

          {error && (
            <div className="registration__error">
              {error}
            </div>
          )}

          <div className="registration__buttons">
            {!isGuest && !confirmResult && (
              <Button
                onClick={handleGuestMode}
                className="registration__button registration__button--guest"
              >
                Mehmon sifatida
              </Button>
            )}

            {isGuest && (
              <Button
                onClick={handleRegisterMode}
                className="registration__button registration__button--register"
              >
                Ro'yxatdan o'tish
              </Button>
            )}

            {((isGuest) || (photo && name.trim())) && (
              <Button
                onClick={handleContinue}
                className="registration__button registration__button--continue"
              >
                Davom etish
              </Button>
            )}
          </div>
        </div>
      </div>
      <canvas ref={canvasRef} style={{ display: 'none' }} />
    </div>
  );
};

export default Registration;
