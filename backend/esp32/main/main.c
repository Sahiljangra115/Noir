#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

void app_main(void) {
    printf("Hello from ESP32! Minimal ESP-IDF app.\n");
    while (1) {
        vTaskDelay(1000 / portTICK_PERIOD_MS);
    }
}
