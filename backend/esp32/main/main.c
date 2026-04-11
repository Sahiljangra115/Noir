#include <ctype.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "driver/gpio.h"
#include "driver/ledc.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"
#include "lwip/sockets.h"
#include "nvs_flash.h"

static const char *TAG = "esp32_controller";

// Update these before flashing.
static const char *WIFI_SSID = "16x2=8";
static const char *WIFI_PASS = "Sahil#115";
static const char *SERVER_IP = "192.168.202.124";
static const uint16_t SERVER_PORT = 9999;

// L298N pins
#define PIN_ENA GPIO_NUM_25
#define PIN_IN1 GPIO_NUM_26
#define PIN_IN2 GPIO_NUM_27
#define PIN_ENB GPIO_NUM_13
#define PIN_IN3 GPIO_NUM_14
#define PIN_IN4 GPIO_NUM_12

#define SPEED_NORMAL 200
#define SPEED_TURN 180

#define WIFI_CONNECTED_BIT BIT0
static EventGroupHandle_t wifi_event_group;

static void set_motors(int left_speed, bool left_fwd, int right_speed, bool right_fwd) {
    ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0, left_speed);
    ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0);
    gpio_set_level(PIN_IN1, left_fwd ? 1 : 0);
    gpio_set_level(PIN_IN2, left_fwd ? 0 : 1);

    ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_1, right_speed);
    ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_1);
    gpio_set_level(PIN_IN3, right_fwd ? 1 : 0);
    gpio_set_level(PIN_IN4, right_fwd ? 0 : 1);
}

static void motor_stop(void) {
    ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0, 0);
    ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0);
    ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_1, 0);
    ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_1);
    gpio_set_level(PIN_IN1, 0);
    gpio_set_level(PIN_IN2, 0);
    gpio_set_level(PIN_IN3, 0);
    gpio_set_level(PIN_IN4, 0);
}

static void execute_command(char cmd) {
    switch (cmd) {
    case 'F':
        set_motors(SPEED_NORMAL, true, SPEED_NORMAL, true);
        break;
    case 'B':
        set_motors(SPEED_NORMAL, false, SPEED_NORMAL, false);
        break;
    case 'L':
        set_motors(SPEED_TURN, false, SPEED_TURN, true);
        break;
    case 'R':
        set_motors(SPEED_TURN, true, SPEED_TURN, false);
        break;
    case 'S':
        motor_stop();
        break;
    default:
        ESP_LOGW(TAG, "Unknown cmd '%c', stopping", cmd);
        motor_stop();
        break;
    }
}

static void init_motors(void) {
    gpio_config_t io_conf = {
        .pin_bit_mask = (1ULL << PIN_IN1) | (1ULL << PIN_IN2) | (1ULL << PIN_IN3) | (1ULL << PIN_IN4),
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    gpio_config(&io_conf);

    ledc_timer_config_t timer = {
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .timer_num = LEDC_TIMER_0,
        .duty_resolution = LEDC_TIMER_8_BIT,
        .freq_hz = 1000,
        .clk_cfg = LEDC_AUTO_CLK,
    };
    ledc_timer_config(&timer);

    ledc_channel_config_t ch0 = {
        .gpio_num = PIN_ENA,
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .channel = LEDC_CHANNEL_0,
        .intr_type = LEDC_INTR_DISABLE,
        .timer_sel = LEDC_TIMER_0,
        .duty = 0,
        .hpoint = 0,
    };
    ledc_channel_config_t ch1 = {
        .gpio_num = PIN_ENB,
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .channel = LEDC_CHANNEL_1,
        .intr_type = LEDC_INTR_DISABLE,
        .timer_sel = LEDC_TIMER_0,
        .duty = 0,
        .hpoint = 0,
    };
    ledc_channel_config(&ch0);
    ledc_channel_config(&ch1);

    motor_stop();
}

static void wifi_event_handler(void *arg, esp_event_base_t event_base, int32_t event_id, void *event_data) {
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        xEventGroupClearBits(wifi_event_group, WIFI_CONNECTED_BIT);
        esp_wifi_connect();
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        xEventGroupSetBits(wifi_event_group, WIFI_CONNECTED_BIT);
    }
    (void)arg;
    (void)event_data;
}

static void init_wifi(void) {
    wifi_event_group = xEventGroupCreate();

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event_handler, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &wifi_event_handler, NULL));

    wifi_config_t wifi_config = {0};
    strncpy((char *)wifi_config.sta.ssid, WIFI_SSID, sizeof(wifi_config.sta.ssid) - 1);
    strncpy((char *)wifi_config.sta.password, WIFI_PASS, sizeof(wifi_config.sta.password) - 1);
    wifi_config.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());

    ESP_LOGI(TAG, "Connecting to WiFi SSID '%s'...", WIFI_SSID);
    xEventGroupWaitBits(wifi_event_group, WIFI_CONNECTED_BIT, pdFALSE, pdTRUE, portMAX_DELAY);
    ESP_LOGI(TAG, "WiFi connected");
}

static int connect_server(void) {
    struct sockaddr_in addr = {
        .sin_family = AF_INET,
        .sin_port = htons(SERVER_PORT),
        .sin_addr.s_addr = inet_addr(SERVER_IP),
    };

    int sock = socket(AF_INET, SOCK_STREAM, IPPROTO_IP);
    if (sock < 0) {
        ESP_LOGE(TAG, "socket() failed errno=%d", errno);
        return -1;
    }

    ESP_LOGI(TAG, "Connecting to %s:%u", SERVER_IP, SERVER_PORT);
    if (connect(sock, (struct sockaddr *)&addr, sizeof(addr)) != 0) {
        ESP_LOGW(TAG, "connect() failed errno=%d", errno);
        close(sock);
        return -1;
    }

    ESP_LOGI(TAG, "Connected to brain server");
    return sock;
}

void app_main(void) {
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    init_motors();
    init_wifi();

    while (1) {
        int sock = connect_server();
        if (sock < 0) {
            motor_stop();
            vTaskDelay(pdMS_TO_TICKS(1000));
            continue;
        }

        while (1) {
            char cmd = 0;
            int n = recv(sock, &cmd, 1, 0);
            if (n <= 0) {
                ESP_LOGW(TAG, "Socket disconnected (n=%d, errno=%d)", n, errno);
                close(sock);
                motor_stop();
                break;
            }

            if (isspace((unsigned char)cmd)) {
                continue;
            }

            ESP_LOGI(TAG, "CMD: %c", cmd);
            execute_command(cmd);
        }

        vTaskDelay(pdMS_TO_TICKS(500));
    }
}
