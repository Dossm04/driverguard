package kz.driverguard.offline;
final class EventText {
    static String label(String kind){return switch(kind){
        case "eyes_closed","microsleep"->"Длительное закрытие глаз";
        case "fatigue","fatigue_perclos"->"Частое закрытие глаз · PERCLOS";
        case "fatigue_yawning"->"Повторные возможные зевки";
        case "yawn"->"Открывание рта / возможный зевок";
        case "head_nod"->"Длительный наклон головы";
        case "face_missing","camera_unavailable"->"Лицо или глаза не видны";
        case "distraction_warning","distraction"->"Длительный поворот головы";
        case "distraction_critical"->"Длительный поворот головы · критический сигнал";
        case "speeding"->"Превышение выбранного лимита";
        case "camera_sabotage"->"Лицо долго не видно при движении";
        case "phone_use"->"Телефон у водителя";
        case "no_seatbelt"->"Ремень не пристёгнут";
        case "smoking"->"Курение";case "sos"->"SOS";default->kind;
    };}
    static String csv(String value){return "\""+(value==null?"":value.replace("\"","\"\""))+"\"";}
}
