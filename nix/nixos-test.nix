{self, ...}: {
  imports = [
  ];
  perSystem = {
    pkgs,
    lib,
    ...
  }: let
    # Mock package for testing
    mockMctomqtt = pkgs.writeShellApplication {
      name = "mctomqtt";
      text = ''
        echo "Mock mctomqtt service - checking environment variables"
        env | grep MCTOMQTT | sort
        echo "Service would normally run here..."
        # Simulate running service
        while true; do sleep 10; done
      '';
    };
  in {
    checks.mctomqtt-test = pkgs.testers.runNixOSTest {
      name = "mctomqtt-test";

      nodes.machine = {
        config,
        pkgs,
        ...
      }: {
        imports = [./nixos-module.nix];

        /*
        # Override the package with our mock for testing
        nixpkgs.overlays = [
          (final: prev: {
            mctomqtt = mockMctomqtt;
          })
        ];
        */

        services.mctomqtt = {
          enable = true;
          package = mockMctomqtt;
          iata = "TEST";
          serialPorts = ["/dev/ttyS1"];

          brokers = [
            {
              enabled = true;
              server = "mqtt1.example.com";
              port = 1883;
              transport = "tcp";
              use-tls = false;
              tls-verify = true;
              client-id-prefix = "test_";
              qos = 1;
              retain = false;
              keepalive = 30;
              username = "user1";
              password = "pass1";
            }
            {
              enabled = true;
              server = "mqtt2.example.com";
              port = 8883;
              transport = "websockets";
              use-tls = true;
              tls-verify = false;
              client-id-prefix = "test2_";
              qos = 2;
              retain = true;
              keepalive = 45;
              username = "user2";
              password = "pass2";
            }
          ];

          settings = {
            serial-baud-rate = 9600;
            serial-timeout = 5;
            log-level = "DEBUG";
            topic-status = "test/{IATA}/{PUBLIC_KEY}/status";
            topic-packets = "test/{IATA}/{PUBLIC_KEY}/packets";
          };
        };
      };

      testScript = ''
        start_all()

        # Wait for the service to start
        machine.wait_for_unit("mctomqtt.service")

        # Check that the service is running
        machine.succeed("systemctl is-active --quiet mctomqtt.service")

        # Verify the user and group were created
        machine.succeed("getent passwd mctomqtt")
        machine.succeed("getent group mctomqtt")

        # Check that the user is in the dialout group
        machine.succeed("groups mctomqtt | grep -q dialout")

        # Check the service's environment variables
        with subtest("Check environment variables"):
          # Basic configuration
          machine.succeed("systemctl show mctomqtt.service | grep -q 'MCTOMQTT_IATA=TEST'")
          machine.succeed("systemctl show mctomqtt.service | grep -q 'MCTOMQTT_SERIAL_PORTS=/dev/ttyS1'")

          # Settings
          machine.succeed("systemctl show mctomqtt.service | grep -q 'MCTOMQTT_SERIAL_BAUD_RATE=9600'")
          machine.succeed("systemctl show mctomqtt.service | grep -q 'MCTOMQTT_SERIAL_TIMEOUT=5'")
          machine.succeed("systemctl show mctomqtt.service | grep -q 'MCTOMQTT_LOG_LEVEL=DEBUG'")
          machine.succeed("systemctl show mctomqtt.service | grep -q 'MCTOMQTT_TOPIC_STATUS=test/{IATA}/{PUBLIC_KEY}/status'")
          machine.succeed("systemctl show mctomqtt.service | grep -q 'MCTOMQTT_TOPIC_PACKETS=test/{IATA}/{PUBLIC_KEY}/packets'")

          # Broker 1 configuration
          machine.succeed("systemctl show mctomqtt.service | grep -q 'MCTOMQTT_MQTT1_ENABLED=true'")
          machine.succeed("systemctl show mctomqtt.service | grep -q 'MCTOMQTT_MQTT1_SERVER=mqtt1.example.com'")
          machine.succeed("systemctl show mctomqtt.service | grep -q 'MCTOMQTT_MQTT1_PORT=1883'")
          machine.succeed("systemctl show mctomqtt.service | grep -q 'MCTOMQTT_MQTT1_TRANSPORT=tcp'")
          machine.succeed("systemctl show mctomqtt.service | grep -q 'MCTOMQTT_MQTT1_USE_TLS=false'")
          machine.succeed("systemctl show mctomqtt.service | grep -q 'MCTOMQTT_MQTT1_TLS_VERIFY=true'")
          machine.succeed("systemctl show mctomqtt.service | grep -q 'MCTOMQTT_MQTT1_CLIENT_ID_PREFIX=test_'")
          machine.succeed("systemctl show mctomqtt.service | grep -q 'MCTOMQTT_MQTT1_QOS=1'")
          machine.succeed("systemctl show mctomqtt.service | grep -q 'MCTOMQTT_MQTT1_RETAIN=false'")
          machine.succeed("systemctl show mctomqtt.service | grep -q 'MCTOMQTT_MQTT1_KEEPALIVE=30'")
          machine.succeed("systemctl show mctomqtt.service | grep -q 'MCTOMQTT_MQTT1_USERNAME=user1'")
          machine.succeed("systemctl show mctomqtt.service | grep -q 'MCTOMQTT_MQTT1_PASSWORD=pass1'")

          # Broker 2 configuration
          machine.succeed("systemctl show mctomqtt.service | grep -q 'MCTOMQTT_MQTT2_ENABLED=true'")
          machine.succeed("systemctl show mctomqtt.service | grep -q 'MCTOMQTT_MQTT2_SERVER=mqtt2.example.com'")
          machine.succeed("systemctl show mctomqtt.service | grep -q 'MCTOMQTT_MQTT2_PORT=8883'")
          machine.succeed("systemctl show mctomqtt.service | grep -q 'MCTOMQTT_MQTT2_TRANSPORT=websockets'")
          machine.succeed("systemctl show mctomqtt.service | grep -q 'MCTOMQTT_MQTT2_USE_TLS=true'")
          machine.succeed("systemctl show mctomqtt.service | grep -q 'MCTOMQTT_MQTT2_TLS_VERIFY=false'")
          machine.succeed("systemctl show mctomqtt.service | grep -q 'MCTOMQTT_MQTT2_CLIENT_ID_PREFIX=test2_'")
          machine.succeed("systemctl show mctomqtt.service | grep -q 'MCTOMQTT_MQTT2_QOS=2'")
          machine.succeed("systemctl show mctomqtt.service | grep -q 'MCTOMQTT_MQTT2_RETAIN=true'")
          machine.succeed("systemctl show mctomqtt.service | grep -q 'MCTOMQTT_MQTT2_KEEPALIVE=45'")
          machine.succeed("systemctl show mctomqtt.service | grep -q 'MCTOMQTT_MQTT2_USERNAME=user2'")
          machine.succeed("systemctl show mctomqtt.service | grep -q 'MCTOMQTT_MQTT2_PASSWORD=pass2'")

        # Check service dependencies
        machine.succeed("systemctl show mctomqtt.service | grep 'After='    | grep -q 'dev-ttyS1.device'")
        machine.succeed("systemctl show mctomqtt.service | grep 'Requires=' | grep -q 'dev-ttyS1.device'")

        # Check service runs as correct user
        machine.succeed("systemctl show mctomqtt.service | grep -q 'User=mctomqtt'")
        machine.succeed("systemctl show mctomqtt.service | grep -q 'Group=mctomqtt'")

        # Check service restart behavior
        machine.succeed("systemctl show mctomqtt.service | grep -q 'Restart=on-failure'")

        # Test that the service can be restarted
        machine.succeed("systemctl restart mctomqtt.service")
        machine.wait_for_unit("mctomqtt.service")
        machine.succeed("systemctl is-active --quiet mctomqtt.service")

        print("All tests passed!")
      '';
    };
  };
}
