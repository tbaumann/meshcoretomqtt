{
  lib,
  config,
  pkgs,
  ...
}: let
  cfg = config.services.mctomqtt;

  # Convert Nix attribute set to environment variables
  settingsToEnv = settings:
    lib.mapAttrsToList (
      name: value: "MCTOMQTT_${lib.toUpper (lib.replaceStrings ["-"] ["_"] name)}=${builtins.toString value}"
    )
    settings;

  # Generate broker environment variables
  brokersToEnv = brokers:
    lib.flatten (lib.imap1 (
        index: broker: let
          prefix = "MCTOMQTT_MQTT${toString index}";
        in
          lib.mapAttrsToList (
            name: value: "${prefix}_${lib.toUpper (lib.replaceStrings ["-"] ["_"] name)}=${builtins.toString value}"
          )
          broker
      )
      brokers);
in {
  options.services.mctomqtt = {
    enable = lib.mkEnableOption "MeshCore to MQTT bridge service";

    package = lib.mkOption {
      type = lib.types.package;
      default = config.defaultPackage.${pkgs.system} or (throw "No default package available for system ${pkgs.system}");
      defaultText = lib.literalExpression "self.packages.${pkgs.system}.default";
      description = "mctomqtt package to use";
    };

    iata = lib.mkOption {
      type = lib.types.strMatching "^[A-Z]{3,4}$";
      example = "XXX";
      description = "Three or four letter IATA code for geographic region";
    };

    serialPorts = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = ["/dev/ttyACM0"];
      description = "Serial ports to listen on (will be available to the mctomqtt user)";
      example = ["/dev/ttyACM0" "/dev/ttyACM1"];
    };

    brokers = lib.mkOption {
      type = lib.types.listOf (lib.types.attrsOf lib.types.anything);
      default = [];
      description = "List of MQTT broker configurations";
      example = lib.literalExpression ''
        [
          {
            enabled = true;
            server = "mqtt.example.com";
            port = 1883;
            transport = "tcp";
            use-tls = false;
            tls-verify = true;
            client-id-prefix = "meshcore_";
            qos = 0;
            retain = true;
            keepalive = 60;
            username = "user";
            password = "pass";
          }
        ]
      '';
    };

    settings = lib.mkOption {
      type = lib.types.attrsOf lib.types.anything;
      default = {};
      description = "Additional settings converted to MCTOMQTT_* environment variables";
      example = lib.literalExpression ''
        {
          serial-baud-rate = 115200;
          serial-timeout = 2;
          log-level = "INFO";
        }
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    # Default package reference for systems that have it
    defaultPackage.${pkgs.system} = lib.mkDefault self.packages.${pkgs.system}.default;

    # Create system user and group
    users.users.mctomqtt = {
      isSystemUser = true;
      group = "mctomqtt";
      description = "MeshCore to MQTT bridge service user";
      extraGroups = ["dialout"]; # For serial port access
    };

    users.groups.mctomqtt = {};

    systemd.services.mctomqtt = {
      description = "MeshCore to MQTT Bridge";
      after = ["network.target"];
      wantedBy = ["multi-user.target"];

      serviceConfig = {
        Type = "simple";
        ExecStart = "${lib.getExe cfg.package}";
        Restart = "on-failure";
        RestartSec = "5s";

        # Run as dedicated user
        User = "mctomqtt";
        Group = "mctomqtt";

        # Runtime directories
        StateDirectory = "mctomqtt";
        CacheDirectory = "mctomqtt";
        LogsDirectory = "mctomqtt";

        # Security settings
        NoNewPrivileges = true;
        PrivateTmp = true;
        ProtectSystem = "strict";
        ProtectHome = true;
        ReadWritePaths =
          [
            "/var/lib/mctomqtt"
            "/var/cache/mctomqtt"
            "/var/log/mctomqtt"
          ]
          ++ cfg.serialPorts;

        # Environment variables
        Environment =
          [
            "MCTOMQTT_IATA=${cfg.iata}"
            "MCTOMQTT_SERIAL_PORTS=${lib.concatStringsSep "," cfg.serialPorts}"
          ]
          ++ settingsToEnv cfg.settings
          ++ brokersToEnv cfg.brokers;
      };

      # Ensure serial devices are available
      unitConfig.Requires = map (port: "dev-${lib.replaceStrings ["/"] [""] port}.device") cfg.serialPorts;
      unitConfig.After = map (port: "dev-${lib.replaceStrings ["/"] [""] port}.device") cfg.serialPorts;
    };
  };
}
