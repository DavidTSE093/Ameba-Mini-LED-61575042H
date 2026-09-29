const int blueLEDPin = LED_B;
const int greenLEDPin = LED_G;
// 被動蜂鳴器或有驅動電路的小喇叭接到此腳位與 GND。
const int speakerPin = 12;

void playFeedback(char type) {
  if (type == '1') { tone(speakerPin, 880, 180); delay(220); }
  else if (type == '2') { tone(speakerPin, 660, 120); delay(150); tone(speakerPin, 990, 180); delay(220); }
  else if (type == '3') { for (int i = 0; i < 3; i++) { tone(speakerPin, 784, 100); delay(140); } }
  else if (type == '4') { tone(speakerPin, 260, 350); delay(390); }
  else { tone(speakerPin, 523, 150); delay(180); tone(speakerPin, 784, 220); delay(250); }
  noTone(speakerPin);
}

void setup() {
  Serial.begin(115200);
  pinMode(blueLEDPin, OUTPUT); pinMode(greenLEDPin, OUTPUT); pinMode(speakerPin, OUTPUT);
  digitalWrite(blueLEDPin, LOW); digitalWrite(greenLEDPin, LOW);
  Serial.println("READY: Ameba LED and audio controller");
}

void loop() {
  if (Serial.available() <= 0) return;
  char command = Serial.read();
  if (command == '\n' || command == '\r') return;
  if (command == 'B') {
    digitalWrite(blueLEDPin, HIGH); digitalWrite(greenLEDPin, LOW);
    Serial.println("Status: Blue LED ON");
  } else if (command == 'G') {
    digitalWrite(blueLEDPin, LOW); digitalWrite(greenLEDPin, HIGH);
    Serial.println("Status: Green LED ON");
  } else if (command == 'F') {
    for (int i = 0; i < 3; i++) {
      digitalWrite(blueLEDPin, HIGH); digitalWrite(greenLEDPin, HIGH); delay(300);
      digitalWrite(blueLEDPin, LOW); digitalWrite(greenLEDPin, LOW); delay(300);
    }
    Serial.println("Status: Flashed 3 times");
  } else if (command == 'Q') {
    Serial.println("PONG: connection is healthy");
  } else if (command == 'T') {
    unsigned long started = millis();
    while (Serial.available() == 0 && millis() - started < 30) delay(1);
    char toneType = Serial.available() > 0 ? Serial.read() : '0';
    playFeedback(toneType);
    Serial.println("Status: Ameba sound played");
  } else {
    Serial.println("Status: Unknown Command");
  }
}
